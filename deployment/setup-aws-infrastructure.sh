#!/bin/bash
# AWS Infrastructure Setup Script for Thakii Backend API
# This script sets up all necessary AWS resources for Lambda deployment

set -e

# Configuration
AWS_REGION=${AWS_REGION:-us-east-2}
FUNCTION_NAME="thakii-backend-api"
GITHUB_USERNAME=${GITHUB_USERNAME:-"oudaykhaled"}
REPO_NAME="thakii-backend-api"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "🚀 Setting up AWS infrastructure for Thakii Backend API"
echo "Account ID: $ACCOUNT_ID"
echo "Region: $AWS_REGION"
echo "Function Name: $FUNCTION_NAME"

# 1. Create S3 bucket for deployment artifacts
DEPLOYMENT_BUCKET="thakii-deployment-artifacts-$ACCOUNT_ID"
echo "📦 Creating S3 bucket for deployment artifacts: $DEPLOYMENT_BUCKET"

if ! aws s3 ls "s3://$DEPLOYMENT_BUCKET" 2>/dev/null; then
    if [ "$AWS_REGION" = "us-east-1" ]; then
        aws s3 mb "s3://$DEPLOYMENT_BUCKET"
    else
        aws s3 mb "s3://$DEPLOYMENT_BUCKET" --region "$AWS_REGION"
    fi
    
    # Enable versioning
    aws s3api put-bucket-versioning \
        --bucket "$DEPLOYMENT_BUCKET" \
        --versioning-configuration Status=Enabled
    
    echo "✅ Deployment bucket created: $DEPLOYMENT_BUCKET"
else
    echo "ℹ️  Deployment bucket already exists: $DEPLOYMENT_BUCKET"
fi

# 2. Create S3 bucket for video storage (if not exists)
VIDEO_STORAGE_BUCKET="thakii-video-storage-$ACCOUNT_ID"
echo "📹 Creating S3 bucket for video storage: $VIDEO_STORAGE_BUCKET"

if ! aws s3 ls "s3://$VIDEO_STORAGE_BUCKET" 2>/dev/null; then
    if [ "$AWS_REGION" = "us-east-1" ]; then
        aws s3 mb "s3://$VIDEO_STORAGE_BUCKET"
    else
        aws s3 mb "s3://$VIDEO_STORAGE_BUCKET" --region "$AWS_REGION"
    fi
    
    # Configure CORS for the video storage bucket
    cat > cors-config.json << EOF
{
    "CORSRules": [
        {
            "AllowedHeaders": ["*"],
            "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
            "AllowedOrigins": ["*"],
            "ExposeHeaders": ["ETag"],
            "MaxAgeSeconds": 3000
        }
    ]
}
EOF
    
    aws s3api put-bucket-cors \
        --bucket "$VIDEO_STORAGE_BUCKET" \
        --cors-configuration file://cors-config.json
    
    rm cors-config.json
    
    echo "✅ Video storage bucket created: $VIDEO_STORAGE_BUCKET"
else
    echo "ℹ️  Video storage bucket already exists: $VIDEO_STORAGE_BUCKET"
fi

# 3. Create GitHub OIDC provider (if not exists)
echo "🔐 Setting up GitHub OIDC provider"

OIDC_PROVIDER_ARN="arn:aws:iam::$ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"

if ! aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_PROVIDER_ARN" 2>/dev/null; then
    aws iam create-open-id-connect-provider \
        --url https://token.actions.githubusercontent.com \
        --client-id-list sts.amazonaws.com \
        --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 \
        --thumbprint-list 1c58a3a8518e8759bf075b76b750d4f2df264fcd
    
    echo "✅ GitHub OIDC provider created"
else
    echo "ℹ️  GitHub OIDC provider already exists"
fi

# 4. Create Lambda execution role
LAMBDA_ROLE_NAME="thakii-lambda-execution-role"
LAMBDA_ROLE_ARN="arn:aws:iam::$ACCOUNT_ID:role/$LAMBDA_ROLE_NAME"

echo "🔑 Creating Lambda execution role: $LAMBDA_ROLE_NAME"

if ! aws iam get-role --role-name "$LAMBDA_ROLE_NAME" 2>/dev/null; then
    aws iam create-role \
        --role-name "$LAMBDA_ROLE_NAME" \
        --assume-role-policy-document file://lambda-trust-policy.json \
        --description "Execution role for Thakii Lambda function"
    
    # Attach basic Lambda execution policy
    aws iam attach-role-policy \
        --role-name "$LAMBDA_ROLE_NAME" \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    
    # Create and attach custom policy
    LAMBDA_POLICY_NAME="thakii-lambda-execution-policy"
    
    # Update the policy document with actual bucket names
    sed "s/thakii-video-storage\*/thakii-video-storage-$ACCOUNT_ID/g" lambda-execution-policy.json > lambda-execution-policy-updated.json
    
    aws iam create-policy \
        --policy-name "$LAMBDA_POLICY_NAME" \
        --policy-document file://lambda-execution-policy-updated.json \
        --description "Custom policy for Thakii Lambda function"
    
    aws iam attach-role-policy \
        --role-name "$LAMBDA_ROLE_NAME" \
        --policy-arn "arn:aws:iam::$ACCOUNT_ID:policy/$LAMBDA_POLICY_NAME"
    
    rm lambda-execution-policy-updated.json
    
    echo "✅ Lambda execution role created: $LAMBDA_ROLE_ARN"
else
    echo "ℹ️  Lambda execution role already exists: $LAMBDA_ROLE_ARN"
fi

# 5. Create GitHub Actions role
GITHUB_ROLE_NAME="thakii-github-actions-role"
GITHUB_ROLE_ARN="arn:aws:iam::$ACCOUNT_ID:role/$GITHUB_ROLE_NAME"

echo "🔑 Creating GitHub Actions role: $GITHUB_ROLE_NAME"

if ! aws iam get-role --role-name "$GITHUB_ROLE_NAME" 2>/dev/null; then
    # Update trust policy with actual values
    sed -e "s/ACCOUNT_ID/$ACCOUNT_ID/g" -e "s/GITHUB_USERNAME/$GITHUB_USERNAME/g" github-trust-policy.json > github-trust-policy-updated.json
    
    aws iam create-role \
        --role-name "$GITHUB_ROLE_NAME" \
        --assume-role-policy-document file://github-trust-policy-updated.json \
        --description "Role for GitHub Actions to deploy Thakii Lambda"
    
    # Create and attach GitHub Actions policy
    GITHUB_POLICY_NAME="thakii-github-actions-policy"
    
    aws iam create-policy \
        --policy-name "$GITHUB_POLICY_NAME" \
        --policy-document file://github-actions-policy.json \
        --description "Policy for GitHub Actions deployment"
    
    aws iam attach-role-policy \
        --role-name "$GITHUB_ROLE_NAME" \
        --policy-arn "arn:aws:iam::$ACCOUNT_ID:policy/$GITHUB_POLICY_NAME"
    
    rm github-trust-policy-updated.json
    
    echo "✅ GitHub Actions role created: $GITHUB_ROLE_ARN"
else
    echo "ℹ️  GitHub Actions role already exists: $GITHUB_ROLE_ARN"
fi

# 6. Create Lambda function
echo "⚡ Creating Lambda function: $FUNCTION_NAME"

if ! aws lambda get-function --function-name "$FUNCTION_NAME" 2>/dev/null; then
    # Create a minimal deployment package
    echo "📦 Creating initial deployment package"
    mkdir -p temp_package
    cat > temp_package/lambda_function.py << 'EOF'
def lambda_handler(event, context):
    return {
        'statusCode': 200,
        'body': '{"message": "Function created, awaiting deployment"}'
    }
EOF
    
    cd temp_package
    zip -r ../initial-package.zip .
    cd ..
    rm -rf temp_package
    
    # Wait for role to be available
    echo "⏳ Waiting for IAM role to be available..."
    sleep 10
    
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.10 \
        --role "$LAMBDA_ROLE_ARN" \
        --handler lambda_handler.lambda_handler \
        --zip-file fileb://initial-package.zip \
        --timeout 30 \
        --memory-size 512 \
        --environment Variables="{S3_BUCKET_NAME=$VIDEO_STORAGE_BUCKET,AWS_REGION=$AWS_REGION}" \
        --description "Thakii Backend API - Flask application on Lambda"
    
    rm initial-package.zip
    
    echo "✅ Lambda function created: $FUNCTION_NAME"
else
    echo "ℹ️  Lambda function already exists: $FUNCTION_NAME"
fi

# 7. Create API Gateway (optional - for direct access)
echo "🌐 Creating API Gateway"

API_NAME="thakii-backend-api"
API_ID=$(aws apigateway get-rest-apis --query "items[?name=='$API_NAME'].id" --output text)

if [ -z "$API_ID" ] || [ "$API_ID" = "None" ]; then
    API_ID=$(aws apigateway create-rest-api \
        --name "$API_NAME" \
        --description "API Gateway for Thakii Backend API" \
        --endpoint-configuration types=REGIONAL \
        --query 'id' --output text)
    
    # Get the root resource ID
    ROOT_RESOURCE_ID=$(aws apigateway get-resources \
        --rest-api-id "$API_ID" \
        --query 'items[?path==`/`].id' --output text)
    
    # Create a proxy resource
    PROXY_RESOURCE_ID=$(aws apigateway create-resource \
        --rest-api-id "$API_ID" \
        --parent-id "$ROOT_RESOURCE_ID" \
        --path-part '{proxy+}' \
        --query 'id' --output text)
    
    # Create ANY method for proxy resource
    aws apigateway put-method \
        --rest-api-id "$API_ID" \
        --resource-id "$PROXY_RESOURCE_ID" \
        --http-method ANY \
        --authorization-type NONE
    
    # Set up Lambda integration
    LAMBDA_URI="arn:aws:apigateway:$AWS_REGION:lambda:path/2015-03-31/functions/arn:aws:lambda:$AWS_REGION:$ACCOUNT_ID:function:$FUNCTION_NAME/invocations"
    
    aws apigateway put-integration \
        --rest-api-id "$API_ID" \
        --resource-id "$PROXY_RESOURCE_ID" \
        --http-method ANY \
        --type AWS_PROXY \
        --integration-http-method POST \
        --uri "$LAMBDA_URI"
    
    # Add Lambda permission for API Gateway
    aws lambda add-permission \
        --function-name "$FUNCTION_NAME" \
        --statement-id "apigateway-invoke-$API_ID" \
        --action lambda:InvokeFunction \
        --principal apigateway.amazonaws.com \
        --source-arn "arn:aws:execute-api:$AWS_REGION:$ACCOUNT_ID:$API_ID/*/*"
    
    # Deploy the API
    aws apigateway create-deployment \
        --rest-api-id "$API_ID" \
        --stage-name prod
    
    API_URL="https://$API_ID.execute-api.$AWS_REGION.amazonaws.com/prod"
    
    echo "✅ API Gateway created: $API_URL"
else
    API_URL="https://$API_ID.execute-api.$AWS_REGION.amazonaws.com/prod"
    echo "ℹ️  API Gateway already exists: $API_URL"
fi

# 8. Create CloudWatch Log Group
LOG_GROUP_NAME="/aws/lambda/$FUNCTION_NAME"
echo "📊 Creating CloudWatch Log Group: $LOG_GROUP_NAME"

if ! aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP_NAME" --query 'logGroups[?logGroupName==`'$LOG_GROUP_NAME'`]' --output text; then
    aws logs create-log-group --log-group-name "$LOG_GROUP_NAME"
    
    # Set retention policy (30 days)
    aws logs put-retention-policy \
        --log-group-name "$LOG_GROUP_NAME" \
        --retention-in-days 30
    
    echo "✅ CloudWatch Log Group created: $LOG_GROUP_NAME"
else
    echo "ℹ️  CloudWatch Log Group already exists: $LOG_GROUP_NAME"
fi

echo ""
echo "🎉 AWS Infrastructure setup complete!"
echo ""
echo "📋 Summary:"
echo "  • Lambda Function: $FUNCTION_NAME"
echo "  • Lambda Role: $LAMBDA_ROLE_ARN"
echo "  • GitHub Actions Role: $GITHUB_ROLE_ARN"
echo "  • Video Storage Bucket: s3://$VIDEO_STORAGE_BUCKET"
echo "  • Deployment Bucket: s3://$DEPLOYMENT_BUCKET"
echo "  • API Gateway URL: $API_URL"
echo "  • CloudWatch Logs: $LOG_GROUP_NAME"
echo ""
echo "🔧 Next steps:"
echo "  1. Add these secrets to your GitHub repository:"
echo "     - AWS_ROLE_ARN: $GITHUB_ROLE_ARN"
echo "     - S3_BUCKET_NAME: $VIDEO_STORAGE_BUCKET"
echo "     - API_GATEWAY_URL: $API_URL"
echo "  2. Configure Firebase service account in GitHub Secrets"
echo "  3. Push code to trigger GitHub Actions deployment"
echo ""
echo "🧪 Test the setup:"
echo "  curl $API_URL/health"
echo ""
