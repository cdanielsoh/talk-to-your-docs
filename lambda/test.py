from document_upload.document_processor import DocumentProcessor
import anthropic
import boto3
import json

collection = "https://ae9gnqfdo2w9uy8heblj.us-west-2.aoss.amazonaws.com"
cr_index_name = "contextual_retrieval_text"
region = "us-west-2"

data_dir = "../data/pdf_docs/shinsegae_live_shopping_guide.pdf"

processor = DocumentProcessor(collection_endpoint=collection, cr_index_name=cr_index_name, region=region)

anthropic_client = anthropic.Anthropic()
bedrock_client = boto3.client("bedrock-runtime", region_name="us-west-2")



# with open(data_dir, 'rb') as pdf_file:
#     pdf_data = pdf_file.read()
#     extracted_text = processor._extract_text(pdf_data)
#     segmented_text = processor._create_segments(extracted_text, "nova")
#     processor._enhance_with_context(segmented_text, extracted_text)
#
