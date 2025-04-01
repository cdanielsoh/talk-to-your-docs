import boto3
import json
import os
import requests
from requests_aws4auth import AWS4Auth
import time


def handler(event, context):
    # Get environment variables
    collection_endpoint = os.environ['COLLECTION_ENDPOINT']
    bucket_name = os.environ['DATA_BUCKET']
    cr_index_name = os.environ['CR_INDEX_NAME']
    kb_index_name = os.environ['KB_INDEX_NAME']
    region = os.environ.get('AWS_REGION')

    # Initialize S3 client
    s3 = boto3.client('s3')

    # Create AWS4Auth for authentication - CRITICAL CHANGE: service is 'aoss' for serverless
    credentials = boto3.Session().get_credentials()
    awsauth = AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        region,
        'aoss',
        session_token=credentials.token
    )

    try:
        # Create the OpenSearch index with mapping
        create_index(collection_endpoint, cr_index_name, awsauth)
        create_index(collection_endpoint, kb_index_name, awsauth)

        # List all JSON files in the bucket
        response = s3.list_objects_v2(Bucket=bucket_name)

        if 'Contents' not in response:
            return {
                'statusCode': 200,
                'body': json.dumps('No files found in the bucket')
            }

        # Process files in batches for bulk indexing
        batch_size = 25
        all_documents = []
        processed_count = 0

        for obj in response['Contents']:
            file_key = obj['Key']
            if file_key.endswith('.pdf.json'):
                try:
                    # Get JSON file from S3
                    file_response = s3.get_object(Bucket=bucket_name, Key=file_key)
                    json_content = json.loads(file_response['Body'].read().decode('utf-8'))

                    # Extract page number from filename
                    page_number = file_key.split('.')[0]

                    # Get the chunk content
                    chunk_content = json_content.get('chunk', '')
                    if not chunk_content:
                        print(f"Skipping {file_key} - no chunk content")
                        continue

                    # Prepare document for indexing
                    document = {
                        'metadata': {
                            'source': file_key,
                            'doc_id': page_number,
                            'timestamp': int(time.time() * 1000)
                        },
                        'content': chunk_content
                    }

                    # Generate embedding for the content
                    embedding = generate_embedding(chunk_content)
                    if embedding:
                        document['content_embedding'] = embedding

                    all_documents.append(document)
                    processed_count += 1

                    # If batch size reached, perform bulk indexing
                    if len(all_documents) >= batch_size:
                        bulk_index_data(collection_endpoint, cr_index_name, all_documents, awsauth)
                        print(f"Indexed batch of {len(all_documents)} documents")
                        all_documents = []

                except Exception as e:
                    print(f"Error processing file {file_key}: {str(e)}")
                    continue

        # Index any remaining documents
        if all_documents:
            bulk_index_data(collection_endpoint, cr_index_name, all_documents, awsauth)
            print(f"Indexed final batch of {len(all_documents)} documents")

        return {
            'statusCode': 200,
            'body': json.dumps(f'Successfully indexed {processed_count} JSON files')
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps(f'Error: {str(e)}')
        }


def create_index(endpoint, index_name, auth):
    url = f"{endpoint}/{index_name}"
    headers = {'Content-Type': 'application/json'}

    # Define the index mapping
    mapping = {
        "settings": {
            "index.knn": True,
            "index.knn.algo_param.ef_search": 512
        },
        "mappings": {
            "properties": {
                "content": {
                    "type": "text",
                    "analyzer": "standard"
                },
                "content_embedding": {
                    "type": "knn_vector",
                    "dimension": 1024,
                    "method": {
                        "engine": "faiss",
                        "name": "hnsw",
                        "parameters": {
                            "ef_construction": 512,
                            "m": 16
                        },
                        "space_type": "l2"
                    }
                }
            }
        }
    }

    # Check if index exists
    try:
        response = requests.head(url, auth=auth, verify=True)
        if response.status_code == 200:
            print(f"Index {index_name} already exists")
            return
    except Exception as e:
        print(f"Error checking if index exists: {str(e)}")

    # Create the index with mapping
    try:
        response = requests.put(url, auth=auth, headers=headers, json=mapping, verify=True)
        print(f"Index creation status code: {response.status_code}")
        print(f"Response body: {response.text}")
        response.raise_for_status()
        print(f"Created index {index_name} with mapping")
    except Exception as e:
        print(f"Error creating index: {str(e)}")
        raise


def bulk_index_data(endpoint, index_name, documents, auth):
    if not documents:
        return

    url = f"{endpoint}/_bulk"
    headers = {'Content-Type': 'application/x-ndjson'}

    # Prepare bulk request body
    bulk_body = ""
    for doc in documents:
        # Create action line (index operation)
        action = {"index": {"_index": index_name}}
        bulk_body += json.dumps(action) + "\n"

        # Create document line
        bulk_body += json.dumps(doc) + "\n"

    try:
        response = requests.post(url, auth=auth, headers=headers, data=bulk_body, verify=True)

        if response.status_code >= 400:
            print(f"Bulk indexing error: {response.text}")
            raise Exception(f"Bulk indexing failed with status code {response.status_code}")
        else:
            print(response.json())
            print(f"Successfully indexed {len(documents)} documents")
    except Exception as e:
        print(f"Error during bulk indexing: {str(e)}")
        raise


def generate_embedding(text):
    try:
        # Initialize Amazon Bedrock Runtime client
        bedrock_runtime = boto3.client('bedrock-runtime')

        # Prepare the request payload
        payload = {
            "inputText": text
        }

        # Call the model - Using Titan Embeddings model
        response = bedrock_runtime.invoke_model(
            modelId="amazon.titan-embed-text-v2:0",
            body=json.dumps(payload)
        )

        # Parse the response
        response_body = json.loads(response['body'].read().decode())
        embedding = response_body.get('embedding', [])

        return embedding

    except Exception as e:
        print(f"Error generating embedding: {str(e)}")
        return None
