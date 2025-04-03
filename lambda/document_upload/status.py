import json
import boto3
import os
from boto3.dynamodb.conditions import Key
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
bedrock = boto3.client('bedrock')


# Custom JSON encoder to handle Decimal types
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def process_token_usage(token_usage):
    """
    Process token usage to handle different formats and ensure consistent output
    """
    if not token_usage:
        return {
            'input_tokens': 0,
            'output_tokens': 0,
            'cache_read_input_tokens': 0,
            'cache_write_input_tokens': 0
        }

    # If token_usage is already processed, return it
    if isinstance(token_usage, dict):
        processed = {}

        # Process each field
        for key, value in token_usage.items():
            # Convert DynamoDB type descriptors if present
            if isinstance(value, dict) and 'N' in value:
                try:
                    processed[key] = int(value['N'])
                except (ValueError, TypeError):
                    processed[key] = 0
            # Convert any string numbers to integers
            elif isinstance(value, str):
                try:
                    processed[key] = int(value)
                except (ValueError, TypeError):
                    processed[key] = 0
            # Keep integers and floats as is
            elif isinstance(value, (int, float, Decimal)):
                processed[key] = value
            # Handle any other case
            else:
                processed[key] = 0

        # Ensure all expected fields exist
        for field in ['input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_write_input_tokens']:
            if field not in processed:
                processed[field] = 0

        return processed

    # For safety, return default values if we can't process
    return {
        'input_tokens': 0,
        'output_tokens': 0,
        'cache_read_input_tokens': 0,
        'cache_write_input_tokens': 0
    }


def handler(event, context):
    """
    Lambda function to get the status of uploaded documents.
    Also checks Bedrock ingestion job status for INGESTING documents.
    """
    try:
        # Get the document table
        document_table = dynamodb.Table(os.environ.get('DOCUMENT_TABLE'))

        # Check for query parameters
        query_params = event.get('queryStringParameters', {})
        if query_params and query_params.get('documentId'):
            # Get a specific document
            document_id = query_params.get('documentId')
            response = document_table.get_item(
                Key={'id': document_id}
            )
            items = [response.get('Item')] if 'Item' in response else []
        else:
            # Get all documents, sorted by upload time (newest first)
            response = document_table.scan()
            items = response.get('Items', [])
            items.sort(key=lambda x: x.get('uploadTime', ''), reverse=True)

        # Update ingestion status for INGESTING documents
        updated_items = []
        for item in items:
            # Process token usage field to ensure consistent format
            if 'tokenUsage' in item:
                item['tokenUsage'] = process_token_usage(item['tokenUsage'])

            # Check OpenSearch statuses
            opensearch_status = item.get('opensearchStatus', {})
            cr_index_status = opensearch_status.get('cr_index', 'PENDING')
            kb_index_status = opensearch_status.get('kb_index', 'PENDING')

            # Add details to the item for frontend display
            item['indexStatus'] = {
                'contextual_retrieval': cr_index_status,
                'knowledge_base': kb_index_status
            }

            # Only check ingestion status for documents that are INGESTING
            if item.get('status') == 'INGESTING' and item.get('ingestionJobId'):
                try:
                    # Get ingestion job status from Bedrock
                    ingestion_job_response = bedrock.get_ingestion_job(
                        knowledgeBaseId=os.environ.get('KNOWLEDGE_BASE_ID'),
                        dataSourceId=os.environ.get('DATA_SOURCE_ID'),
                        ingestionJobId=item.get('ingestionJobId')
                    )

                    job_status = ingestion_job_response.get('status')

                    # If job status has changed, update in DynamoDB
                    if job_status != item.get('ingestionStatus'):
                        update_expr = "SET ingestionStatus = :status"
                        expr_attrs = {':status': job_status}

                        # If job is complete, update document status
                        if job_status == 'COMPLETE':
                            update_expr += ", opensearchStatus.kb_index = :kbstatus"
                            expr_attrs[':kbstatus'] = 'COMPLETED'

                            # Check if both indexes are now complete
                            if cr_index_status == 'COMPLETED':
                                update_expr += ", #st = :docstatus, statusMessage = :msg"
                                expr_attrs[':docstatus'] = 'COMPLETED'
                                expr_attrs[
                                    ':msg'] = 'Document has been successfully processed and is ready for querying'

                        # If job failed, update document status
                        elif job_status == 'FAILED':
                            update_expr += ", opensearchStatus.kb_index = :kbstatus"
                            expr_attrs[':kbstatus'] = 'ERROR'

                            # Set overall status to error
                            update_expr += ", #st = :docstatus, statusMessage = :msg"
                            expr_attrs[':docstatus'] = 'ERROR'
                            err_msg = ingestion_job_response.get('failureReason', 'Unknown error during ingestion')
                            expr_attrs[':msg'] = f'Ingestion failed: {err_msg}'

                        # Update item in DynamoDB if needed
                        try:
                            document_table.update_item(
                                Key={'id': item['id']},
                                UpdateExpression=update_expr,
                                ExpressionAttributeValues=expr_attrs,
                                ExpressionAttributeNames={'#st': 'status'}
                            )

                            # Also update our local copy for the response
                            item['ingestionStatus'] = job_status

                            if ':kbstatus' in expr_attrs:
                                item['opensearchStatus']['kb_index'] = expr_attrs[':kbstatus']
                                item['indexStatus']['knowledge_base'] = expr_attrs[':kbstatus']

                            if ':docstatus' in expr_attrs:
                                item['status'] = expr_attrs[':docstatus']
                                item['statusMessage'] = expr_attrs[':msg']
                        except Exception as update_error:
                            print(f"Error updating document status: {str(update_error)}")

                except Exception as e:
                    print(f"Error checking ingestion job status: {str(e)}")

            # For items with both indexes as PROCESSING, check if both are complete
            if (item.get('status') == 'PROCESSING' and
                    cr_index_status == 'COMPLETED' and kb_index_status == 'COMPLETED'):
                try:
                    # Update overall status to COMPLETED
                    document_table.update_item(
                        Key={'id': item['id']},
                        UpdateExpression="SET #status = :status, statusMessage = :msg",
                        ExpressionAttributeNames={'#status': 'status'},
                        ExpressionAttributeValues={
                            ':status': 'COMPLETED',
                            ':msg': 'Document has been fully processed and is ready for use'
                        }
                    )

                    # Update our local copy
                    item['status'] = 'COMPLETED'
                    item['statusMessage'] = 'Document has been fully processed and is ready for use'
                except Exception as update_error:
                    print(f"Error updating document status: {str(update_error)}")

            updated_items.append(item)

        # Return the document information using custom JSON encoder to handle Decimal types
        return {
            'statusCode': 200,
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Allow-Methods': 'OPTIONS,GET'
            },
            'body': json.dumps({
                'documents': updated_items
            }, cls=DecimalEncoder)  # Use the custom encoder here
        }

    except Exception as e:
        print(f"Error getting document status: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Allow-Methods': 'OPTIONS,GET'
            },
            'body': json.dumps({'error': str(e)})
        }


def handler_options(event, context):
    """Handle OPTIONS requests for CORS"""
    return {
        'statusCode': 200,
        'headers': {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Allow-Methods': 'OPTIONS,GET'
        },
        'body': ''
    }