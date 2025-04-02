import aws_cdk as cdk
from constructs import Construct
from aws_cdk import (
    aws_lambda as lambda_,
    aws_apigatewayv2 as apigatewayv2,
    aws_apigatewayv2_integrations as integrations,
    aws_iam as iam,
    aws_s3 as s3,
    aws_s3_deployment as s3_deployment,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_dynamodb as dynamodb,
    Duration,
    CustomResource
)
from aws_cdk.custom_resources import (
    Provider
)
import os
import json


class BedrockChatbotStack(cdk.Stack):
    def __init__(self, scope: Construct, id: str, kb_id, kb_document_url, kb_outputs, **kwargs):
        super().__init__(scope, id, **kwargs)

        # Extract OpenSearch details from knowledge base outputs
        opensearch_endpoint = kb_outputs.get("opensearch_endpoint")
        opensearch_index = kb_outputs.get("index_name")

        # Create DynamoDB table to store WebSocket connections
        connections_table = dynamodb.Table(
            self, 'ConnectionsTable',
            partition_key=dynamodb.Attribute(
                name='connectionId',
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # Create Lambda functions for WebSocket routes
        connect_function = lambda_.Function(
            self, 'ConnectFunction',
            runtime=lambda_.Runtime.PYTHON_3_9,
            handler='connect.handler',
            code=lambda_.Code.from_asset('lambda/websocket'),
            environment={
                'CONNECTIONS_TABLE': connections_table.table_name,
            },
        )

        disconnect_function = lambda_.Function(
            self, 'DisconnectFunction',
            runtime=lambda_.Runtime.PYTHON_3_9,
            handler='disconnect.handler',
            code=lambda_.Code.from_asset('lambda/websocket'),
            environment={
                'CONNECTIONS_TABLE': connections_table.table_name,
            },
        )

        # Create Lambda layer for OpenSearch integration
        opensearch_layer = lambda_.LayerVersion(
            self, 'OpenSearchLayer',
            code=lambda_.Code.from_asset('layers/opensearch.zip'),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_9],
            description='Layer containing the OpenSearch SDK'
        )

        # Create Bedrock Lambda function with both KnowledgeBase and OpenSearch access
        bedrock_function = lambda_.Function(
            self, 'BedrockLambdaFunction',
            runtime=lambda_.Runtime.PYTHON_3_9,
            handler='message.handler',
            code=lambda_.Code.from_asset('lambda/websocket'),
            layers=[opensearch_layer],
            environment={
                'KNOWLEDGE_BASE_ID': kb_id,
                'REGION': 'us-west-2',
                'CONNECTIONS_TABLE': connections_table.table_name,
                'OPENSEARCH_ENDPOINT': opensearch_endpoint,
                'OPENSEARCH_INDEX': opensearch_index,
                'RESPONSE_LANGUAGE': 'Korean'
            },
            timeout=Duration.minutes(5),
            memory_size=1024
        )

        # Grant permissions to Lambda functions
        connections_table.grant_read_write_data(connect_function)
        connections_table.grant_read_write_data(disconnect_function)
        connections_table.grant_read_write_data(bedrock_function)

        # Grant Bedrock permissions to Lambda
        bedrock_function.add_to_role_policy(iam.PolicyStatement(
            actions=[
                'bedrock:RetrieveAndGenerate',
                'bedrock:Retrieve',
                'bedrock:InvokeModelWithResponseStream',
                'bedrock:InvokeModel',
                'bedrock:Rerank'
            ],
            resources=['*'],
        ))

        # Grant OpenSearch Serverless permissions
        bedrock_function.add_to_role_policy(iam.PolicyStatement(
            actions=['aoss:APIAccessAll'],
            resources=['*'],
        ))

        # Create WebSocket API
        websocket_api = apigatewayv2.WebSocketApi(
            self, 'BedrockWebSocketAPI',
            connect_route_options=apigatewayv2.WebSocketRouteOptions(
                integration=integrations.WebSocketLambdaIntegration(
                    'ConnectIntegration', connect_function
                )
            ),
            disconnect_route_options=apigatewayv2.WebSocketRouteOptions(
                integration=integrations.WebSocketLambdaIntegration(
                    'DisconnectIntegration', disconnect_function
                )
            ),
            default_route_options=apigatewayv2.WebSocketRouteOptions(
                integration=integrations.WebSocketLambdaIntegration(
                    'MessageIntegration', bedrock_function
                )
            ),
        )

        # Add permissions for Lambda to post to connections
        websocket_stage = apigatewayv2.WebSocketStage(
            self, 'BedrockWebSocketStage',
            web_socket_api=websocket_api,
            stage_name='prod',
            auto_deploy=True,
        )

        # Grant permission for Bedrock Lambda to manage WebSocket connections
        bedrock_function.add_to_role_policy(iam.PolicyStatement(
            actions=['execute-api:ManageConnections'],
            resources=[f'arn:aws:execute-api:{self.region}:{self.account}:{websocket_api.api_id}/*'],
        ))

        # Create S3 bucket for hosting React website
        website_bucket = s3.Bucket(
            self, 'ReactWebsiteBucket',
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # CloudFront Origin Access Identity for S3
        origin_access_identity = cloudfront.OriginAccessIdentity(
            self, 'OAI',
            comment=f'OAI for {id} website'
        )

        # Grant read permissions to CloudFront
        website_bucket.grant_read(origin_access_identity)

        # Create CloudFront distribution
        distribution = cloudfront.Distribution(
            self, 'WebsiteDistribution',
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3Origin(
                    website_bucket,
                    origin_access_identity=origin_access_identity
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                origin_request_policy=cloudfront.OriginRequestPolicy.CORS_S3_ORIGIN,
            ),
            default_root_object="index.html",
            error_responses=[
                # For SPA routing, redirect all 404s to index.html
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                )
            ],
        )

        config_path = os.path.join('document_chatbot_ui', 'build', 'config.json')
        config_content = {
            'websocketUrl': websocket_stage.url,
            'cloudfrontDomain': kb_document_url
        }

        with open(config_path, 'w') as f:
            json.dump(config_content, f)

        website_deployment = s3_deployment.BucketDeployment(
            self, 'DeployWebsite',
            sources=[s3_deployment.Source.asset('./document_chatbot_ui/build')],
            destination_bucket=website_bucket,
            distribution=distribution,
            distribution_paths=['/*'],
            role=iam.Role(
                self, "DeploymentRole",
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
                                    "cloudfront:GetInvalidation"  # Add this permission
                                ],
                                resources=["*"]
                            )
                        ]
                    )
                }
            )
        )

        # Lambda to update config.json with actual values
        update_config_lambda = lambda_.Function(
            self, 'UpdateConfigFunction',
            runtime=lambda_.Runtime.PYTHON_3_9,
            handler='index.handler',
            code=lambda_.Code.from_asset('lambda/update_config'),
            environment={
                'WEBSOCKET_URL': websocket_stage.url,
                'CLOUDFRONT_DOMAIN': kb_document_url,  # Pass from constructor
                'WEBSITE_BUCKET': website_bucket.bucket_name,
                'DISTRIBUTION_ID': distribution.distribution_id
            },
            timeout=Duration.minutes(5)
        )

        # Grant permissions
        website_bucket.grant_read_write(update_config_lambda)

        update_config_lambda.add_to_role_policy(iam.PolicyStatement(
            actions=[
                "cloudfront:CreateInvalidation",
                "cloudfront:GetInvalidation"
            ],
            resources=["*"]
        ))

        # Custom resource to trigger Lambda after deployment
        config_updater = CustomResource(
            self, 'ConfigUpdaterResource',
            service_token=Provider(
                self, 'ConfigUpdaterProvider',
                on_event_handler=update_config_lambda
            ).service_token
        )

        # Make sure this runs after the website is deployed
        config_updater.node.add_dependency(website_deployment)

        # Output the WebSocket API URL
        cdk.CfnOutput(
            self, 'WebSocketURL',
            value=websocket_stage.url,
            description='URL of the WebSocket API',
        )

        # Output the CloudFront distribution URL
        cdk.CfnOutput(
            self, 'WebsiteURL',
            value=f'https://{distribution.distribution_domain_name}',
            description='URL of the website',
        )