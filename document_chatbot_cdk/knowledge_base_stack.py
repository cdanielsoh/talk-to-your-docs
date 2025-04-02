from aws_cdk import (
    Stack,
    aws_opensearchserverless as opensearchserverless,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_lambda as lambda_,
    aws_bedrock as bedrock,
    RemovalPolicy,
    CustomResource,
    CfnOutput,
    Duration,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_iam as iam,
    CfnDeletionPolicy,
    aws_sqs as sqs,
    aws_lambda_event_sources as lambda_event_sources
)
from aws_cdk.custom_resources import Provider
from constructs import Construct
import json
from datetime import datetime
from typing import TypedDict


class KnowledgebaseStackOutputs(TypedDict):
    opensearch_endpoint: str
    index_name: str
    knowledgebase_id: str
    document_cloudfront_url: str


class KnowledgebaseStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, use_parallel_processing, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.use_parallel_processing = use_parallel_processing

        document_bucket = s3.Bucket(
            self, "DocumentBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True
        )

        supplemental_data_bucket = s3.Bucket(
            self, "SupplementalDataBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True
        )

        document_data_upload = s3deploy.BucketDeployment(
            self, "DeployDocumentData",
            sources=[s3deploy.Source.asset("./data/pdf_docs")],
            destination_bucket=document_bucket,
            role=iam.Role(
                self, "DocumentDeploymentRole",
                assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
                managed_policies=[
                    iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
                ],
                inline_policies={
                    "CloudFrontInvalidation": iam.PolicyDocument(
                        statements=[
                            iam.PolicyStatement(
                                actions=[
                                    "cloudfront:CreateInvalidation",
                                    "cloudfront:GetInvalidation"
                                ],
                                resources=["*"]
                            )
                        ]
                    )
                }
            )
        )

        # Create Origin Access Identity for CloudFront
        origin_access_identity = cloudfront.OriginAccessIdentity(
            self, 'DocumentBucketOAI',
            comment=f'OAI for accessing document bucket {document_bucket.bucket_name}'
        )

        # Grant read permissions to CloudFront
        document_bucket.grant_read(origin_access_identity)

        # Create CloudFront distribution for document access
        document_distribution = cloudfront.Distribution(
            self, 'DocumentDistribution',
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3Origin(
                    document_bucket,
                    origin_access_identity=origin_access_identity
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                cached_methods=cloudfront.CachedMethods.CACHE_GET_HEAD,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                origin_request_policy=cloudfront.OriginRequestPolicy.CORS_S3_ORIGIN,
                response_headers_policy=cloudfront.ResponseHeadersPolicy.CORS_ALLOW_ALL_ORIGINS,
            ),
            enable_logging=True,
            price_class=cloudfront.PriceClass.PRICE_CLASS_100
        )

        document_distribution.node.add_dependency(document_data_upload)

        # Define a valid collection name
        collection_name = f"collection-{self.account}"
        contextual_retrieval_index_name = "contextual_retrieval_text"
        knowledgebase_index_name = "knowledgebase"

        # Lambda role with necessary permissions (moved earlier for policy references)
        lambda_role = iam.Role(
            self, "IngestLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com")
        )

        lambda_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
        )

        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "aoss:APIAccessAll",
                    "aoss:List*",
                    "aoss:Create*",
                    "aoss:Update*",
                    "aoss:Delete*",
                ],
                resources=["*"]
            )
        )

        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",  # Required for model inference
                    "bedrock:ListFoundationModels",  # Optional for model discovery
                    "bedrock:GetFoundationModel"  # Optional for model details
                ],
                resources=[
                    "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2:0",
                    "arn:aws:bedrock:*::foundation-model/anthropic.claude-3-5-haiku-20241022-v1:0",
                ]
            )
        )

        # 1. Create Encryption Policy (required before collection)
        encryption_policy = opensearchserverless.CfnSecurityPolicy(
            self, "CollectionEncryptionPolicy",
            name=f"encryption-policy",
            type="encryption",
            policy=json.dumps({
                "Rules": [{
                    "ResourceType": "collection",
                    "Resource": [f"collection/{collection_name}"]
                }],
                "AWSOwnedKey": True
            })
        )

        encryption_policy.cfn_options.deletion_policy = CfnDeletionPolicy.DELETE

        # 2. Create Network Policy
        network_policy = opensearchserverless.CfnSecurityPolicy(
            self, "CollectionNetworkPolicy",
            name=f"network-policy",
            type="network",
            policy=json.dumps([{
                "Rules": [{
                    "ResourceType": "collection",
                    "Resource": [f"collection/{collection_name}"]
                }, {
                    "ResourceType": "dashboard",
                    "Resource": [f"collection/{collection_name}"]
                }],
                "AllowFromPublic": True  # For demo purposes only
            }])
        )

        network_policy.cfn_options.deletion_policy = CfnDeletionPolicy.DELETE

        # 3. Create OpenSearch Serverless Collection
        collection = opensearchserverless.CfnCollection(
            self, "DocumentsSearchCollection",
            name=collection_name,
            type="VECTORSEARCH",
            description="Collection for contextual retrieval"
        )

        collection.cfn_options.deletion_policy = CfnDeletionPolicy.DELETE

        # Add dependencies to ensure proper creation order
        collection.add_dependency(encryption_policy)
        collection.add_dependency(network_policy)

        # 4. Create Data Access Policy with proper format
        data_access_policy = opensearchserverless.CfnAccessPolicy(
            self, "CollectionAccessPolicy",
            name=f"data-access-policy",
            type="data",
            policy=json.dumps([{
                "Rules": [
                    {
                        "ResourceType": "index",
                        "Resource": [f"index/{collection_name}/*"],
                        "Permission": ["aoss:*"]
                    },
                    {
                        "ResourceType": "collection",
                        "Resource": [f"collection/{collection_name}"],
                        "Permission": ["aoss:*"]
                    }
                ],
                "Principal": [
                    lambda_role.role_arn,
                    f"arn:aws:iam::{self.account}:root"
                ]  # Use actual IAM role ARN instead of "*"
            }])
        )

        # Add dependency to ensure collection exists before access policy
        data_access_policy.add_dependency(collection)
        data_access_policy.add_dependency(encryption_policy)
        data_access_policy.add_dependency(network_policy)
        data_access_policy.cfn_options.deletion_policy = CfnDeletionPolicy.DELETE

        # Requests layer
        requests_layer = lambda_.LayerVersion(
            self, "RequestsLayer",
            code=lambda_.Code.from_asset("./layers/requests.zip"),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description="Layer containing the requests module"
        )

        pdfplumber_layer = lambda_.LayerVersion(
            self, "PdfPlumberLayer",
            code=lambda_.Code.from_asset("layers/pdfplumber_layer.zip"),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description="Layer containing pdfplumber and dependencies"
        )

        # Grant S3 access
        document_bucket.grant_read(lambda_role)

        # Create index initializer Lambda
        index_initializer = lambda_.Function(
            self, "IndexInitializerFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index_initializer.handler",
            code=lambda_.Code.from_asset("./lambda/knowledge_base"),
            environment={
                "COLLECTION_ENDPOINT": f"{collection.attr_collection_endpoint}",
                "CR_INDEX_NAME": contextual_retrieval_index_name,
                "KB_INDEX_NAME": knowledgebase_index_name,
                "REGION": self.region
            },
            timeout=Duration.minutes(5),
            layers=[requests_layer],
            role=lambda_role  # Use the same role as other Lambdas
        )

        # Ensure Lambda waits for access policy to be created
        index_initializer.node.add_dependency(data_access_policy)
        index_initializer.node.add_dependency(collection)

        # Create a custom resource that triggers the index initializer
        index_init_trigger = CustomResource(
            self, "IndexInitTrigger",
            service_token=Provider(
                self, "IndexInitProvider",
                on_event_handler=index_initializer
            ).service_token,
            properties={
                "Timestamp": datetime.now().isoformat()  # Force update on each deployment
            }
        )

        # Add dependencies
        index_init_trigger.node.add_dependency(collection)
        index_init_trigger.node.add_dependency(data_access_policy)
        index_init_trigger.node.add_dependency(document_data_upload)

        if self.use_parallel_processing:

            pdf_processing_queue = sqs.Queue(
                self, "PDFProcessingQueue",
                visibility_timeout=Duration.minutes(30),
                retention_period=Duration.minutes(60)
            )

            queue_initiator = lambda_.Function(
                self, "QueueInitiatorFunction",
                runtime=lambda_.Runtime.PYTHON_3_12,
                handler="queue_initiator.handler",
                code=lambda_.Code.from_asset("./lambda/knowledge_base"),
                environment={
                    "PDF_BUCKET": document_bucket.bucket_name,
                    "SQS_QUEUE_URL": pdf_processing_queue.queue_url
                },
                timeout=Duration.minutes(5)
            )

            document_bucket.grant_read(queue_initiator)
            pdf_processing_queue.grant_send_messages(queue_initiator)

            # Create a custom resource that triggers the queue initiator
            queue_trigger = CustomResource(
                self, "QueueInitiatorTrigger",
                service_token=Provider(
                    self, "QueueInitiatorProvider",
                    on_event_handler=queue_initiator
                ).service_token,
                properties={
                    "Timestamp": datetime.now().isoformat()  # Force update on each deployment
                }
            )

            # Add dependencies
            queue_trigger.node.add_dependency(index_init_trigger)
            queue_trigger.node.add_dependency(document_data_upload)
            queue_trigger.node.add_dependency(pdf_processing_queue)
            queue_trigger.node.add_dependency(collection)

            # Create the document processor Lambda
            doc_processor = lambda_.Function(
                self, "DocumentProcessorFunction",
                runtime=lambda_.Runtime.PYTHON_3_12,
                handler="document_processor.handler",
                code=lambda_.Code.from_asset("./lambda/knowledge_base"),
                environment={
                    "COLLECTION_ENDPOINT": f"{collection.attr_collection_endpoint}",
                    "CR_INDEX_NAME": contextual_retrieval_index_name,
                    "KB_INDEX_NAME": knowledgebase_index_name,
                    "REGION": self.region
                },
                timeout=Duration.minutes(15),  # Maximum Lambda timeout
                memory_size=2048,
                layers=[requests_layer, pdfplumber_layer],
                role=lambda_role
            )

            # Add SQS as event source
            doc_processor.add_event_source(
                lambda_event_sources.SqsEventSource(pdf_processing_queue,
                    batch_size=1  # Process one document at a time
                )
            )

            # Ensure Lambda waits for access policy to be created
            doc_processor.node.add_dependency(data_access_policy)

            # Grant S3 access
            document_bucket.grant_read(doc_processor)

        else:
            sequential_processor = lambda_.Function(
                self, "SequentialProcessorFunction",
                runtime=lambda_.Runtime.PYTHON_3_12,
                handler="sequential_processor.handler",
                code=lambda_.Code.from_asset("./lambda/knowledge_base"),
                environment={
                    "COLLECTION_ENDPOINT": f"{collection.attr_collection_endpoint}",
                    "DATA_BUCKET": document_bucket.bucket_name,
                    "CR_INDEX_NAME": contextual_retrieval_index_name,
                    "REGION": self.region
                },
                timeout=Duration.minutes(15),
                memory_size=2048,
                layers=[requests_layer, pdfplumber_layer],
                role=lambda_role
            )

            document_bucket.grant_read(sequential_processor)

            sequential_trigger = CustomResource(
                self, "SequentialProcessorTrigger",
                service_token=Provider(
                    self, "SequentialProvider",
                    on_event_handler=sequential_processor
                ).service_token,
                properties={
                    "Timestamp": datetime.now().isoformat()
                }
            )

            sequential_trigger.node.add_dependency(index_init_trigger)
            sequential_trigger.node.add_dependency(document_data_upload)

        # Create IAM role for Bedrock Knowledge Base
        knowledge_base_role = iam.Role(
            self, 'KnowledgeBaseRole',
            assumed_by=iam.ServicePrincipal('bedrock.amazonaws.com'),
        )

        # Add S3 permissions to the role
        knowledge_base_role.add_to_policy(iam.PolicyStatement(
            actions=[
                's3:GetObject',
                's3:ListBucket',
                's3:PutObject', 
                's3:DeleteObject'
            ],
            resources=[
                document_bucket.bucket_arn,
                f'{document_bucket.bucket_arn}/*',
                supplemental_data_bucket.bucket_arn,
                f'{supplemental_data_bucket.bucket_arn}/*'
            ],
        ))

        # Add OpenSearch permissions to the role
        knowledge_base_role.add_to_policy(iam.PolicyStatement(
            actions=[
                'aoss:APIAccessAll'
            ],
            resources=[collection.attr_arn],
        ))

        # Add Bedrock permissions to the role
        knowledge_base_role.add_to_policy(iam.PolicyStatement(
            actions=[
                'bedrock:*'
            ],
            resources=['*'],
        ))

        # Create Data Access Policy for Bedrock Knowledge Base
        bedrock_data_access_policy = opensearchserverless.CfnAccessPolicy(
            self, 'BedrockDataAccessPolicy',
            name='bedrock-access-policy',
            type='data',
            description='Data access policy for development',
            policy=json.dumps([
                {
                    'Rules': [
                        {
                            'ResourceType': 'collection',
                            'Resource': [f'collection/{collection_name}'],
                            'Permission': [
                                'aoss:CreateCollectionItems',
                                'aoss:DeleteCollectionItems',
                                'aoss:UpdateCollectionItems',
                                'aoss:DescribeCollectionItems',
                                'aoss:*'
                            ]
                        },
                        {
                            'ResourceType': 'index',
                            'Resource': [f"index/{collection_name}/*"],
                            'Permission': [
                                'aoss:CreateIndex',
                                'aoss:DeleteIndex',
                                'aoss:UpdateIndex',
                                'aoss:DescribeIndex',
                                'aoss:ReadDocument',
                                'aoss:WriteDocument',
                                'aoss:*'
                            ]
                        }
                    ],
                    'Principal': [
                        knowledge_base_role.role_arn,
                        index_initializer.role.role_arn,
                        f'arn:aws:iam::{self.account}:root'
                    ],
                    'Description': 'Combined access policy for both collection and index operations'
                }
            ])
        )

        # Add dependencies
        collection.add_dependency(encryption_policy)
        collection.add_dependency(network_policy)
        bedrock_data_access_policy.add_dependency(collection)
        bedrock_data_access_policy.cfn_options.deletion_policy = CfnDeletionPolicy.DELETE

        # Create Knowledge Base
        knowledgebase_name = 'knowledge-base'
        knowledge_base = bedrock.CfnKnowledgeBase(
            self, 'BedrockKnowledgeBase',
            name=knowledgebase_name,
            role_arn=knowledge_base_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type='VECTOR',
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=f'arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0',
                    supplemental_data_storage_configuration=bedrock.CfnKnowledgeBase.SupplementalDataStorageConfigurationProperty(
                        supplemental_data_storage_locations=[bedrock.CfnKnowledgeBase.SupplementalDataStorageLocationProperty(
                            supplemental_data_storage_location_type="S3",
                            s3_location=bedrock.CfnKnowledgeBase.S3LocationProperty(
                                uri=f"s3://{supplemental_data_bucket.bucket_name}"
                            )
                        )]
                    )
                )
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type='OPENSEARCH_SERVERLESS',
                opensearch_serverless_configuration=bedrock.CfnKnowledgeBase.OpenSearchServerlessConfigurationProperty(
                    collection_arn=collection.attr_arn,
                    field_mapping=bedrock.CfnKnowledgeBase.OpenSearchServerlessFieldMappingProperty(
                        metadata_field='metadata',
                        text_field='content',
                        vector_field='content_embedding',
                    ),
                    vector_index_name=knowledgebase_index_name,
                ),
            ),
        )

        # Add dependency to ensure index exists before Knowledge Base creation
        knowledge_base.node.add_dependency(document_data_upload)
        knowledge_base.node.add_dependency(index_init_trigger)
        knowledge_base.node.add_dependency(index_initializer)
        knowledge_base.node.add_dependency(bedrock_data_access_policy)
        knowledge_base.cfn_options.deletion_policy = CfnDeletionPolicy.DELETE

        data_source = bedrock.CfnDataSource(
            self, 'BedrockDataSource',
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=document_bucket.bucket_arn,
                ),
                type='S3'
            ),
            knowledge_base_id=knowledge_base.attr_knowledge_base_id,
            name='document-datasource',
            description='Data source for documents',
            data_deletion_policy='RETAIN',
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
                    chunking_strategy='HIERARCHICAL',
                    hierarchical_chunking_configuration=bedrock.CfnDataSource.HierarchicalChunkingConfigurationProperty(
                        level_configurations=[
                            bedrock.CfnDataSource.HierarchicalChunkingLevelConfigurationProperty(
                                max_tokens=1000
                            ),
                            bedrock.CfnDataSource.HierarchicalChunkingLevelConfigurationProperty(
                                max_tokens=200
                            )
                        ],
                        overlap_tokens=60
                    )
                ),
                parsing_configuration=bedrock.CfnDataSource.ParsingConfigurationProperty(
                    parsing_strategy='BEDROCK_FOUNDATION_MODEL',
                    bedrock_foundation_model_configuration=bedrock.CfnDataSource.BedrockFoundationModelConfigurationProperty(
                        model_arn=f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
                        parsing_modality="MULTIMODAL"
                    )
                )
            )
        )
        
        data_source.node.add_dependency(knowledge_base)

        # After creating your knowledge base and data source
        kb_sync_lambda = lambda_.Function(
            self, 'KBSyncFunction',
            runtime=lambda_.Runtime.PYTHON_3_9,
            handler='index.handler',
            code=lambda_.Code.from_asset('lambda/kb_sync'),
            environment={
                'KNOWLEDGE_BASE_ID': knowledge_base.attr_knowledge_base_id,
                'DATA_SOURCE_ID': data_source.attr_data_source_id,
                'REGION': 'us-west-2',
            },
            timeout=Duration.minutes(5)
        )

        # Grant permissions to sync the knowledge base
        kb_sync_lambda.add_to_role_policy(iam.PolicyStatement(
            actions=[
                'bedrock:StartIngestionJob',
                'bedrock:GetIngestionJob',
                'bedrock:ListIngestionJobs',
            ],
            resources=['*'],
        ))

        # Create a Custom Resource to trigger the sync
        sync_trigger = CustomResource(
            self, 'KBSyncTrigger',
            service_token=Provider(
                self, 'KBSyncProvider',
                on_event_handler=kb_sync_lambda,
            ).service_token
        )

        # Make sure the sync happens after knowledge base creation
        sync_trigger.node.add_dependency(knowledge_base)
        sync_trigger.node.add_dependency(data_source)

        self.outputs: KnowledgebaseStackOutputs = {
            "opensearch_endpoint": collection.attr_collection_endpoint,
            "index_name": contextual_retrieval_index_name,
            "knowledgebase_id": knowledge_base.attr_knowledge_base_id,
            "document_cloudfront_url": document_distribution.distribution_domain_name
        }

        # Output the collection endpoint and bucket name
        CfnOutput(self, "CollectionEndpoint", value=collection.attr_collection_endpoint)
        CfnOutput(self, "DataBucketName", value=document_bucket.bucket_name)
        CfnOutput(self, "DashboardsURL", value=f"https://{collection.attr_dashboard_endpoint}/_dashboards/")
        CfnOutput(self, "KnowledgeBaseId", value=knowledge_base.attr_knowledge_base_id)
        CfnOutput(
            self, 'DocumentCloudFrontUrl',
            value=document_distribution.distribution_domain_name,
            description='CloudFront URL for accessing documents',
        )
