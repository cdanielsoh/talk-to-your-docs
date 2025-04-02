import boto3
import json
import os
import io
import pdfplumber
import requests
import re
from datetime import datetime
from requests_aws4auth import AWS4Auth
from botocore.config import Config
from document_processor import DocumentProcessor


def handler(event, context):
    """Lambda handler that processes all PDFs sequentially"""
    print(f"Event received: {json.dumps(event)}")

    # Get environment variables
    collection_endpoint = os.environ['COLLECTION_ENDPOINT']
    bucket_name = os.environ['DATA_BUCKET']
    cr_index_name = os.environ['CR_INDEX_NAME']
    region = os.environ.get('REGION') or os.environ.get('AWS_REGION')

    # Initialize processor
    processor = DocumentProcessor(
        collection_endpoint=collection_endpoint,
        cr_index_name=cr_index_name,
        region=region
    )

    # List PDF files in the bucket
    s3 = boto3.client('s3')
    response = s3.list_objects_v2(Bucket=bucket_name)

    if 'Contents' not in response:
        print(f"No files found in bucket {bucket_name}")
        return {
            'statusCode': 200,
            'body': 'No files found in bucket'
        }

    # Filter for PDF files only
    pdf_files = [obj['Key'] for obj in response['Contents']
                 if obj['Key'].lower().endswith('.pdf')]

    if not pdf_files:
        print(f"No PDF files found in bucket {bucket_name}")
        return {
            'statusCode': 200,
            'body': 'No PDF files found in bucket'
        }

    # Process each PDF file sequentially
    total_processed = 0
    files_processed = 0

    for pdf_file in pdf_files:
        try:
            # Get file from S3
            response = s3.get_object(Bucket=bucket_name, Key=pdf_file)
            pdf_content = response['Body'].read()

            # Process document
            s3_uri = f"s3://{bucket_name}/{pdf_file}"
            segments_indexed = processor.process_document(pdf_content, pdf_file, s3_uri)

            print(f"Successfully processed {pdf_file}: indexed {segments_indexed} segments")

            total_processed += segments_indexed
            files_processed += 1

        except Exception as e:
            print(f"Error processing {pdf_file}: {str(e)}")

    print(f"Processing complete: {files_processed} files processed, {total_processed} segments indexed")

    return {
        'statusCode': 200,
        'body': json.dumps({
            'filesProcessed': files_processed,
            'segmentsIndexed': total_processed
        })
    }


class DocumentProcessor:
    """Handles PDF document processing including extraction, segmentation, and indexing"""

    def __init__(self, collection_endpoint, cr_index_name, region):
        self.collection_endpoint = collection_endpoint
        self.cr_index_name = cr_index_name
        self.region = region

        # Configuration parameters
        self.segment_size = 1000  # Size of text segments
        self.segment_overlap = 200  # Overlap between segments
        self.enable_context = True  # Whether to add contextual information

        # Initialize Bedrock client with retry config
        retry_config = Config(
            region_name=region,
            retries={"max_attempts": 5, "mode": "standard"}
        )
        self.bedrock_client = boto3.client("bedrock-runtime", config=retry_config)

        # Create AWS4Auth for OpenSearch
        credentials = boto3.Session().get_credentials()
        self.auth = AWS4Auth(
            credentials.access_key,
            credentials.secret_key,
            region,
            'aoss',
            session_token=credentials.token
        )

    def process_document(self, pdf_content, document_name, source_uri):
        """Process a PDF document from content bytes"""
        # Extract text from PDF
        document_text = self._extract_text(pdf_content)
        if not document_text:
            print(f"No text extracted from {document_name}")
            return 0

        # Create segments from document text
        segments = self._create_segments(document_text, document_name)
        print(f"Created {len(segments)} segments from {document_name}")

        # Add contextual information if enabled
        if self.enable_context:
            segments = self._enhance_with_context(segments, document_text)

        # Index segments to OpenSearch
        indexed_count = self._index_segments(segments, document_name, source_uri)

        return indexed_count

    def _extract_text(self, pdf_bytes):
        """Extract text from PDF content"""
        all_text = ""
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        # Clean and normalize text
                        text = re.sub(r'\s+', ' ', text).strip()
                        all_text += text + " "
            return all_text.strip()
        except Exception as e:
            print(f"Error extracting text from PDF: {e}")
            return ""

    def _create_segments(self, text, document_name):
        """Split text into semantic segments at natural boundaries"""
        segments = []

        # Split at sentence boundaries
        sentences = re.split(r'(?<=[.!?])\s+', text)
        current_segment = ""
        segment_id = 0

        for sentence in sentences:
            # If adding this sentence would exceed the segment size and we already have content
            if len(current_segment) + len(sentence) > self.segment_size and current_segment:
                segment_id += 1
                segments.append({
                    "id": f"{document_name}_segment_{segment_id}",
                    "content": current_segment.strip(),
                    "position": segment_id
                })

                # Start new segment with overlap
                overlap_text = current_segment.split(".")[-1] if "." in current_segment else ""
                current_segment = overlap_text + " " + sentence
            else:
                # Add to current segment
                current_segment += " " + sentence

        # Add the last segment if not empty
        if current_segment.strip():
            segment_id += 1
            segments.append({
                "id": f"{document_name}_segment_{segment_id}",
                "content": current_segment.strip(),
                "position": segment_id
            })

        return segments

    def _enhance_with_context(self, segments, full_document):
        """Add contextual information to each segment using LLM"""
        enhanced_segments = []

        system_message = {"text": """
        You are a document context specialist. Your task is to briefly describe how a text segment 
        fits within a larger document. Provide 2-3 sentences that:
        1. Identify the key information in this segment
        2. Explain how this segment relates to the broader content
        Be concise and specific.
        Answer in Korean.
        """}

        for segment in segments:
            try:
                user_message = {"role": "user", "content": [{"text": f"""
                <document>
                {full_document}... [document continues]
                </document>

                <segment>
                {segment["content"]}
                </segment>

                Describe how this segment fits into the broader context.
                """}]}

                response = self.bedrock_client.converse(
                    modelId="anthropic.claude-3-5-haiku-20241022-v1:0",
                    messages=[user_message],
                    system=[system_message],
                    inferenceConfig={"temperature": 0.0, "topP": 0.5},
                )

                context_description = response['output']['message']['content'][0]['text'].strip()
                segment["enhanced_content"] = f"Context: {context_description}\n\nContent: {segment['content']}"
                enhanced_segments.append(segment)

            except Exception as e:
                print(f"Error enhancing segment {segment['id']}: {e}")
                # Use original content as fallback
                segment["enhanced_content"] = segment["content"]
                enhanced_segments.append(segment)

        return enhanced_segments

    def _get_embedding(self, text):
        """Generate vector embedding for text"""
        try:
            response = self.bedrock_client.invoke_model(
                modelId="amazon.titan-embed-text-v2:0",
                body=json.dumps({"inputText": text})
            )

            response_body = json.loads(response['body'].read())
            return response_body.get('embedding')

        except Exception as e:
            print(f"Error generating embedding: {e}")
            return None

    def _index_segments(self, segments, document_name, source_uri):
        """Index segments to OpenSearch"""
        batch_size = 20
        current_batch = []
        indexed_count = 0

        for segment in segments:
            # Use enhanced content if available
            content_to_index = segment.get("enhanced_content", segment["content"])

            # Generate embedding
            embedding = self._get_embedding(content_to_index)
            if not embedding:
                print(f"Skipping segment {segment['id']} - embedding failed")
                continue

            # Create document for indexing with simple metadata
            doc = {
                "content": content_to_index,
                "content_embedding": embedding,
                "metadata": {
                    "source": source_uri,
                    "doc_id": document_name,
                    "chunk_id": segment["id"],
                    "timestamp": datetime.now().isoformat()
                }
            }

            current_batch.append(doc)

            # Process batch if reached batch size
            if len(current_batch) >= batch_size:
                success = self._bulk_index(current_batch)
                if success:
                    indexed_count += len(current_batch)
                current_batch = []

        # Process any remaining documents
        if current_batch:
            success = self._bulk_index(current_batch)
            if success:
                indexed_count += len(current_batch)

        return indexed_count

    def _bulk_index(self, documents):
        """Index batch of documents to OpenSearch"""
        if not documents:
            return True

        url = f"{self.collection_endpoint}/_bulk"
        headers = {'Content-Type': 'application/x-ndjson'}

        # Prepare bulk request body
        bulk_body = ""
        for doc in documents:
            # Add action line
            action = {"index": {"_index": self.cr_index_name}}
            bulk_body += json.dumps(action) + "\n"

            # Add document line
            bulk_body += json.dumps(doc) + "\n"

        try:
            response = requests.post(
                url,
                auth=self.auth,
                headers=headers,
                data=bulk_body,
                verify=True
            )

            if response.status_code >= 400:
                print(f"Bulk indexing error: {response.text}")
                return False
            else:
                print(f"Successfully indexed {len(documents)} documents")
                return True

        except Exception as e:
            print(f"Bulk indexing exception: {e}")
            return False