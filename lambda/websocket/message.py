import boto3
import os
import json
from botocore.exceptions import BotoCoreError, ClientError

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['CONNECTIONS_TABLE'])

# Default model if none specified
DEFAULT_MODEL = 'anthropic.claude-3-sonnet-20240229-v1:0'

# Map of allowed models - this is for security to prevent arbitrary model injection
ALLOWED_MODELS = {
    'amazon.nova-pro-v1:0': 'arn:aws:bedrock:us-west-2::foundation-model/amazon.nova-pro-v1:0',
    'amazon.nova-lite-v1:0': 'arn:aws:bedrock:us-west-2::foundation-model/amazon.nova-lite-v1:0',
    'anthropic.claude-3-7-sonnet-20250219-v1:0': 'arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-3-7-sonnet-20250219-v1:0',
    'anthropic.claude-3-5-sonnet-20241022-v2:0': 'arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0',
    'anthropic.claude-3-5-haiku-20241022-v1:0': 'arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-3-5-haiku-20241022-v1:0'
}


def handler(event, context):
    # Get connection ID
    connection_id = event['requestContext']['connectionId']

    # Parse message from client
    body = json.loads(event['body'])
    query = body.get('query', '')

    # Get model ID from request
    model_id = body.get('modelArn', DEFAULT_MODEL)

    # Security check: only use model if it's in our allowed list
    if model_id not in ALLOWED_MODELS:
        print(f"WARNING: Requested model {model_id} not in allowed list, using default")
        model_id = DEFAULT_MODEL

    # Get the model ARN
    model_arn = ALLOWED_MODELS[model_id]
    print(f"Using model: {model_id} with ARN: {model_arn}")

    # Get search method if provided
    search_method = body.get('searchMethod', 'opensearch')
    print(f"Using search method: {search_method}")

    # Get endpoint URL for sending messages
    domain = event['requestContext']['domainName']
    stage = event['requestContext']['stage']
    endpoint = f"https://{domain}/{stage}"

    # Set up API Gateway management client
    apigw_management = boto3.client(
        'apigatewaymanagementapi',
        endpoint_url=endpoint
    )

    # Get the knowledge base details
    knowledge_base_id = os.environ['KNOWLEDGE_BASE_ID']
    region = os.environ['REGION']

    # Create Bedrock client
    client = boto3.client('bedrock-agent-runtime', region_name=region)

    try:
        # Initiate streaming response from Bedrock
        response = client.retrieve_and_generate_stream(
            input={'text': query},
            retrieveAndGenerateConfiguration={
                'type': 'KNOWLEDGE_BASE',
                'knowledgeBaseConfiguration': {
                    'knowledgeBaseId': knowledge_base_id,
                    'modelArn': model_arn
                }
            }
        )

        citation_count = 0
        source_map = {}  # Maps source URLs to citation numbers

        # Process streaming response
        for event in response['stream']:
            # Stream text output
            if 'output' in event:
                text_chunk = event['output']['text']
                send_to_connection(apigw_management, connection_id, {
                    'type': 'text',
                    'content': text_chunk
                })

            # Process citations
            if 'citation' in event:
                try:
                    citations = event.get('citation', {}).get('retrievedReferences', [])
                    for citation in citations:
                        # Extract source URL
                        source_url = extract_source_url(citation)

                        if source_url:
                            # Only assign a new citation number if this source hasn't been seen before
                            if source_url not in source_map:
                                citation_count += 1
                                source_map[source_url] = citation_count

                                # Send the citation marker to be inserted in the text stream
                                citation_marker = f" [{citation_count}] "
                                send_to_connection(apigw_management, connection_id, {
                                    'type': 'text',
                                    'content': citation_marker
                                })

                                # Also send citation information for the document viewer
                                send_to_connection(apigw_management, connection_id, {
                                    'type': 'citation',
                                    'sourceId': str(citation_count),
                                    'sourceUrl': source_url
                                })
                except Exception as citation_error:
                    print(f"Error processing citation: {str(citation_error)}")

        # Send completion message with all source references
        send_to_connection(apigw_management, connection_id, {
            'type': 'complete',
            'sources': {str(num): url for url, num in source_map.items()}
        })

    except Exception as e:
        error_message = str(e)
        print(f"Error processing request: {error_message}")
        send_to_connection(apigw_management, connection_id, {
            'type': 'error',
            'message': error_message
        })

    return {
        'statusCode': 200,
        'body': 'Streaming process completed'
    }


def send_to_connection(apigw_client, connection_id, data):
    """Send data to the WebSocket connection."""
    try:
        apigw_client.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(data)
        )
    except Exception as e:
        print(f"Error sending message to connection {connection_id}: {str(e)}")


def extract_source_url(citation):
    """Extract source URL from citation based on location type."""
    try:
        if 'location' in citation:
            location = citation['location']

            # Handle S3 location
            if 'type' in location and location['type'] == 'S3' and 's3Location' in location:
                return location['s3Location']['uri']

            # Handle web location
            elif 'type' in location and location['type'] == 'WEB' and 'webLocation' in location:
                return location['webLocation']['url']

            # Try to find any location with uri/url field
            else:
                for loc_key in location:
                    if isinstance(location[loc_key], dict):
                        if 'uri' in location[loc_key]:
                            return location[loc_key]['uri']
                        elif 'url' in location[loc_key]:
                            return location[loc_key]['url']
    except Exception as e:
        print(f"Error extracting source URL: {str(e)}")

    return None