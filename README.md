# WordPress MCP Server

A Machine Communication Protocol (MCP) server that allows publishing content to WordPress sites.

## Features

- Publish articles to WordPress
- Test WordPress connection
- Retrieve WordPress categories and tags
- Works as both standalone FastAPI server and MCP server

## Setup

1. Create a virtual environment using UV:
   ```
   uv venv
   .venv\Scripts\activate
   ```

2. Install dependencies:
   ```
   uv pip install -r requirements.txt
   ```

3. Configure WordPress credentials:
   - Rename `.env.example` to `.env` (or create a new `.env` file)
   - Update with your WordPress site URL, username, and application password

## Usage

### As MCP Server

Run the server in MCP mode:
```
python main.py --mcp
```

### As Standalone API

Run the server as a standalone FastAPI application:
```
python main.py
```

The API will be available at http://localhost:8000

## API Endpoints

- `GET /` - Root endpoint
- `GET /wp-config` - Get WordPress configuration from environment variables
- `POST /get-categories` - Get all categories from WordPress
- `POST /get-tags` - Get all tags from WordPress
- `POST /test-connection` - Test the WordPress connection
- `POST /publish-article` - Publish an article to WordPress

## MCP Tools

- `PUBLISH_ARTICLE` - Publish an article to WordPress
- `TEST_CONNECTION` - Test connection to WordPress site
- `GET_CATEGORIES` - Get list of categories from WordPress site
- `GET_TAGS` - Get list of tags from WordPress site