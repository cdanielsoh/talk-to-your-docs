import boto3
import os
import json
import cfnresponse
import time


def handler(event, context):
    try:
        print(f"Starting KB sync handler with event: {event}")
        if event['RequestType'] in ['Create', 'Update']:
            kb_id = os.environ['KNOWLEDGE_BASE_ID']
            ds_id = os.environ['DATA_SOURCE_ID']
            region = os.environ['REGION']

            bedrock = boto3.client('bedrock', region_name=region)

            # Start ingestion job
            response = bedrock.start_ingestion_job(
                knowledgeBaseId=kb_id,
                dataSourceId=ds_id
            )

            ingestion_job_id = response['ingestionJob']['ingestionJobId']
            print(f"Started ingestion job: {ingestion_job_id}")

            # Optional: Wait for job to complete (may timeout for large datasets)
            max_wait_time = 240  # seconds
            wait_interval = 10  # seconds
            elapsed_time = 0

            while elapsed_time < max_wait_time:
                job_status = bedrock.get_ingestion_job(
                    knowledgeBaseId=kb_id,
                    dataSourceId=ds_id,
                    ingestionJobId=ingestion_job_id
                )

                status = job_status['ingestionJob']['status']
                print(f"Job status: {status}")

                if status in ['COMPLETE', 'FAILED', 'STOPPED']:
                    break

                time.sleep(wait_interval)
                elapsed_time += wait_interval

            cfnresponse.send(event, context, cfnresponse.SUCCESS, {
                'IngestionJobId': ingestion_job_id,
                'Status': status if elapsed_time < max_wait_time else 'STILL_RUNNING'
            })
        else:
            # Nothing to do for Delete
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
    except Exception as e:
        print(f"Error in KB sync: {str(e)}")
        cfnresponse.send(event, context, cfnresponse.FAILED, {'Error': str(e)})