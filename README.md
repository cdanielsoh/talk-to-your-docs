# Document Chatbot with AWS Bedrock

A full-stack application that creates a chat interface for your PDF documents using AWS Bedrock, Amazon OpenSearch Serverless, and AWS CDK.
It displays the source PDF when providing answers.

## Features

- **Document Intelligence**: Automatically extracts, processes, and understands PDF documents
- **Vector Search**: Uses OpenSearch Serverless for semantic search capabilities
- **Conversational Interface**: Chat with your documents using natural language
- **LLM Integration**: Powered by AWS Bedrock models (Claude, Amazon Nova Pro)
- **Real-time Streaming**: Responses stream in real-time via WebSockets
- **Document Viewer**: Integrated PDF viewer to reference source documents
- **Mobile-Responsive**: Works on desktop and mobile devices
- **Serverless Architecture**: Fully serverless deployment for scalability

## Architecture Overview

The application consists of two main stacks:

1. **Knowledge Base Stack** - Creates and manages:
   - OpenSearch Serverless Collection for vector search
   - AWS Bedrock Knowledge Base
   - PDF document storage and processing
   - Document CloudFront distribution

2. **Web Stack** - Builds and deploys:
   - WebSocket API for real-time communication
   - React web application
   - CloudFront distribution

## Prerequisites

- AWS Account with appropriate permissions
- AWS CLI configured with your credentials
- Node.js (version 14+) and npm installed
- Python 3.9+ installed
- AWS CDK installed (`npm install -g aws-cdk`)

## Setup Instructions

### Step 1: Clone the Repository and Install Dependencies

```bash
# Clone the repository
git clone https://github.com/cdanielsoh/talk-to-your-docs.git
cd talk-to-your-docs

# Initialize Python virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Install CDK dependencies
npm install -g aws-cdk
cdk --version  # Verify CDK installation
```

### Step 2: Prepare Your PDF Documents

1. Place your PDF documents in the `data/pdf_docs/` directory.
   ```bash
   # Create directory if it doesn't exist
   mkdir -p data/pdf_docs
   
   # Copy your PDF files into the directory
   cp your-documents/*.pdf data/pdf_docs/
   ```

2. Make sure your PDF files are text-based and not scanned images (for better extraction results).

### Step 3: Build the React Web Application

The React application needs to be built before deployment:

```bash
# Navigate to the React app directory
cd document_chatbot_ui

# Install dependencies
npm install

# Build the application
npm run build

# Return to the project root
cd ..
```

### Step 4: Deploy the CDK Stacks

The application can be deployed in two modes:

#### Option A: Sequential Processing (Recommended for Small Document Sets)

```bash
# Deploy with sequential processing (default)
cdk deploy --all
```

Sequential processing is simpler and works well for smaller document sets (up to ~10 PDFs). All documents are processed by a single Lambda function in sequence.

#### Option B: Parallel Processing (For Larger Document Sets)

```bash
# Deploy with parallel processing
cdk deploy --context use_parallel_processing=true --all
```

Parallel processing uses SQS and multiple Lambda invocations to process documents in parallel, which is more efficient for larger document sets but adds complexity.

### Step 5: Monitor the Deployment

The deployment creates several resources and may take 10-15 minutes to complete. The CDK output will show you:

1. The CloudFront URL for your web application
2. The WebSocket URL for real-time communication
3. The Knowledge Base ID

You can monitor the document ingestion process in the AWS Bedrock console.

## Using the Application

1. Open the web application using the CloudFront URL provided in the CDK output.
2. Choose a model (e.g., Claude 3.5 Sonnet or Amazon Nova Pro) from the dropdown.
3. Select a search method:
   - Knowledge Base (OpenSearch): Uses AWS Bedrock Knowledge Bases
   - Contextual Retrieval: Uses direct vector search via OpenSearch, where each chunk is enhanced with context

4. Ask questions about your documents in the chat interface.
5. The application will display relevant document sources in the right panel.

## Customization Options

### Language Support

By default, the chatbot is configured to respond in Korean. To change this:

1. Modify the `RESPONSE_LANGUAGE` environment variable in `document_chatbot_cdk/bedrock_chatbot_cdk_stack.py`

### Adding More Models

To add additional Bedrock models:

1. Update the model list in `document_chatbot_ui/src/components/Selector/Selector.jsx`
2. Add the corresponding model ARN in `lambda/websocket/message.py`

## Troubleshooting

### PDF Processing Issues

If your documents aren't being processed correctly:

1. Check that the PDFs contain extractable text (not scanned images)
2. Verify the Lambda logs in CloudWatch for any processing errors
3. Try reprocessing documents by updating them in the S3 bucket

### Connection Issues

If you experience connection problems with the web interface:

1. Check the browser console for WebSocket errors
2. Verify that the WebSocket API Gateway service is running
3. Review the Lambda logs for any connection handling errors

### OpenSearch Issues

If document search isn't working:

1. Check the OpenSearch Serverless dashboard for the collection status
2. Verify index creation and document ingestion in the CloudWatch logs
3. Test document retrieval directly through the AWS Bedrock console

## Cost Considerations

This application uses several AWS services that incur costs:

- AWS Bedrock (pay per API request)
- OpenSearch Serverless (pay for compute and storage)
- AWS Lambda (pay per invocation and duration)
- Amazon S3 and CloudFront (pay for storage and data transfer)

Consider setting up AWS Budgets to monitor your costs, especially if you're processing large document sets or expecting high traffic.

## Clean Up

To avoid incurring charges, delete the stacks when you're done:

```bash
cdk destroy --all
```

This will remove all resources except for S3 buckets with data. You'll need to empty and delete those buckets manually from the AWS Console.
