# WordPress MCP Server

A Machine Communication Protocol (MCP) server that allows publishing content to WordPress sites.

## Features

- Publish articles to WordPress
- Test WordPress connection
- Create, retrieve, and manage WordPress categories and tags
- Automatically handle category and tag creation when publishing
- Support for featured images via URL or base64-encoded data
- Works as both standalone FastAPI server and MCP server
- Environment variable support for WordPress credentials

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

- `PUBLISH_ARTICLE` - Publish an article to WordPress with category and tag IDs
- `PREPARE_ARTICLE_METADATA` - Check for existing categories and tags, create them if they don't exist, and return their IDs
- `TEST_CONNECTION` - Test connection to WordPress site

## Category and Tag Management

The WordPress MCP Server now supports advanced category and tag management:

### Using PREPARE_ARTICLE_METADATA

This tool allows you to:
1. Check if categories and tags exist on your WordPress site
2. Automatically create any categories or tags that don't exist
3. Return the IDs of all categories and tags for use with PUBLISH_ARTICLE

Example workflow:
1. Call PREPARE_ARTICLE_METADATA with category and tag names
2. Get back the corresponding IDs
3. Use those IDs with PUBLISH_ARTICLE to publish your content

## Featured Image Support

The WordPress MCP Server now supports adding featured images to articles:

### Using PUBLISH_ARTICLE with Images

You can add a featured image to your article in two ways:

1. **Via URL**: Provide an `image_url` parameter with a direct link to the image
   ```
   "image_url": "https://example.com/path/to/image.jpg"
   ```

2. **Via Base64**: Provide an `image_base64` parameter with the base64-encoded image data
   ```
   "image_base64": "iVBORw0KGgoAAAANSUhEUgAA..."
   ```

3. **Custom Filename**: Optionally specify a filename for the uploaded image
   ```
   "image_filename": "my-custom-image-name.jpg"
   ```

The server will:
- Download the image (if URL provided) or decode the base64 data
- Upload the image to WordPress
- Set it as the featured image for the article
- Return the media ID in the response

### Using the Standalone API

When using the standalone API, you can provide a featured image either as:
- A file upload using the `image` form field
- A URL using the `image_url` form field

## Environment Variable Support

All tools now support using environment variables from your `.env` file as defaults:
- `WP_SITE_URL` - Your WordPress site URL
- `WP_USERNAME` - Your WordPress username
- `WP_PASSWORD` - Your WordPress application password

This means you can call the tools without explicitly providing these parameters if they're set in your environment.