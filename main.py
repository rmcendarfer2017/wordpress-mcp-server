import os
import sys
import json
import base64
import asyncio
import logging
import traceback
from typing import Optional, List, Dict, Any, Union
from enum import Enum

import requests
from fastapi import FastAPI, Form, File, UploadFile, HTTPException, Depends, Header, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="WordPress MCP Server")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models
class WordPressConfig(BaseModel):
    site_url: str
    username: str
    password: str
    
    def __init__(self, **data):
        # Ensure site_url has a protocol
        if "site_url" in data and data["site_url"] and not data["site_url"].startswith(("http://", "https://")):
            data["site_url"] = f"http://{data['site_url']}"
        super().__init__(**data)

class ArticleRequest(BaseModel):
    title: str
    content: str
    excerpt: Optional[str] = None
    status: str = "draft"  # draft, publish, pending, private
    categories: Optional[List[int]] = None
    tags: Optional[List[int]] = None
    featured_media_id: Optional[int] = None

class ArticleResponse(BaseModel):
    article_id: int
    article_url: str
    status: str
    edit_url: Optional[str] = None

# Helper functions
def get_wp_auth(config: WordPressConfig):
    """Generate WordPress authentication token"""
    # For Application Passwords, spaces don't matter, so remove them
    password = config.password.replace(" ", "")
    
    # Generate the authentication token
    token = base64.b64encode(f"{config.username}:{password}".encode()).decode()
    
    return {"Authorization": f"Basic {token}"}

def upload_media_to_wordpress(image_data: bytes, filename: str, config: WordPressConfig):
    """Upload media to WordPress and return the media ID"""
    headers = get_wp_auth(config)
    headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    headers["Content-Type"] = "image/jpeg"  # Adjust based on file type if needed
    
    upload_url = f"{config.site_url}/wp-json/wp/v2/media"
    response = requests.post(upload_url, data=image_data, headers=headers)
    
    if response.status_code not in (201, 200):
        raise HTTPException(status_code=response.status_code, detail=f"Failed to upload media: {response.text}")
    
    return response.json().get("id")

# Routes
@app.get("/")
async def root():
    return {"message": "WordPress MCP Server"}

@app.get("/wp-config")
async def get_wp_config():
    """Get WordPress configuration from environment variables"""
    return {
        "site_url": os.getenv("WP_SITE_URL", ""),
        "username": os.getenv("WP_USERNAME", ""),
        "password": os.getenv("WP_PASSWORD", "")
    }

@app.post("/get-categories")
async def get_categories(
    site_url: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
):
    """Get all categories from WordPress"""
    config = WordPressConfig(site_url=site_url, username=username, password=password)
    headers = get_wp_auth(config)
    
    # Get all categories (up to 100)
    categories_url = f"{config.site_url}/wp-json/wp/v2/categories?per_page=100"
    response = requests.get(categories_url, headers=headers)
    
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch categories: {response.text}")
    
    categories = response.json()
    
    # Return simplified list for API response
    return {
        "status": "success",
        "categories": [
            {
                "id": cat.get("id"),
                "name": cat.get("name"),
                "slug": cat.get("slug"),
                "count": cat.get("count", 0)
            } for cat in categories
        ]
    }

@app.post("/get-tags")
async def get_tags(
    site_url: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
):
    """Get all tags from WordPress"""
    config = WordPressConfig(site_url=site_url, username=username, password=password)
    headers = get_wp_auth(config)
    
    # Get all tags (up to 100)
    tags_url = f"{config.site_url}/wp-json/wp/v2/tags?per_page=100"
    response = requests.get(tags_url, headers=headers)
    
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch tags: {response.text}")
    
    tags = response.json()
    
    # Return simplified list for API response
    return {
        "status": "success",
        "tags": [
            {
                "id": tag.get("id"),
                "name": tag.get("name"),
                "slug": tag.get("slug"),
                "count": tag.get("count", 0)
            } for tag in tags
        ]
    }

@app.get("/test-connection")
async def test_connection():
    """Test the WordPress connection using environment variables"""
    site_url = os.getenv("WP_SITE_URL", "")
    username = os.getenv("WP_USERNAME", "")
    password = os.getenv("WP_PASSWORD", "")
    
    if not site_url or not username or not password:
        return {"status": "error", "message": "Missing WordPress credentials in environment variables"}
    
    # Ensure site_url has protocol
    if not site_url.startswith(("http://", "https://")):
        site_url = f"http://{site_url}"
    
    # Create config
    config = WordPressConfig(site_url=site_url, username=username, password=password)
    
    # Test connection by fetching users
    headers = get_wp_auth(config)
    try:
        response = requests.get(f"{config.site_url}/wp-json/wp/v2/users/me", headers=headers)
        
        if response.status_code == 200:
            user_data = response.json()
            return {
                "status": "success", 
                "message": f"Successfully connected to WordPress as {user_data.get('name')}",
                "user": user_data
            }
        else:
            return {
                "status": "error", 
                "message": f"Failed to authenticate: {response.status_code} {response.reason}",
                "details": response.text
            }
    except Exception as e:
        return {"status": "error", "message": f"Connection error: {str(e)}"}

@app.post("/publish", response_model=ArticleResponse)
async def publish_article(
    title: str = Form(...),
    content: str = Form(...),
    excerpt: Optional[str] = Form(None),
    status: str = Form("draft"),
    categories: str = Form("[]"),  # JSON string of category IDs
    tags: str = Form("[]"),  # JSON string of tag IDs
    image: Optional[UploadFile] = File(None),
    site_url: str = Form(os.getenv("WP_SITE_URL", "")),
    username: str = Form(os.getenv("WP_USERNAME", "")),
    password: str = Form(os.getenv("WP_PASSWORD", "")),
):
    """
    Publish an article to WordPress with optional image, categories, and tags
    """
    # Parse inputs
    try:
        categories_list = json.loads(categories)
        tags_list = json.loads(tags)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format for categories or tags")
    
    # Set up WordPress connection
    config = WordPressConfig(site_url=site_url, username=username, password=password)
    headers = get_wp_auth(config)
    
    # Upload image if provided
    featured_media_id = None
    if image:
        image_data = await image.read()
        featured_media_id = upload_media_to_wordpress(image_data, image.filename, config)
    
    # Create article payload
    article_data = {
        "title": title,
        "content": content,
        "status": status,
    }
    
    if excerpt:
        article_data["excerpt"] = excerpt
    if categories_list:
        article_data["categories"] = categories_list
    if tags_list:
        article_data["tags"] = tags_list
    if featured_media_id:
        article_data["featured_media"] = featured_media_id
    
    # Publish article with all data in a single request
    posts_url = f"{config.site_url}/wp-json/wp/v2/posts"
    response = requests.post(posts_url, headers=headers, json=article_data)
    
    if response.status_code not in (201, 200):
        raise HTTPException(status_code=response.status_code, detail=f"Failed to publish article: {response.text}")
    
    result = response.json()
    edit_url = f"{config.site_url}/wp-admin/post.php?post={result.get('id')}&action=edit"
    return ArticleResponse(
        article_id=result.get("id"),
        article_url=result.get("link", ""),
        status=result.get("status", "unknown"),
        edit_url=edit_url
    )

# MCP Server integration
try:
    from mcp.server.models import InitializationOptions
    import mcp.types as types
    from mcp.server import NotificationOptions, Server
    import mcp.server.stdio
    
    print("MCP library successfully imported", file=sys.stderr)
    
    # Initialize MCP Server with the name matching mcp_config.json
    server = Server("wordpress-publish")
    
    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """
        List available tools for WordPress publishing.
        """
        return [
            types.Tool(
                name="PUBLISH_ARTICLE",
                description="Publish an article to WordPress with optional image, categories, and tags",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Article title"},
                        "content": {"type": "string", "description": "Article content in HTML format"},
                        "excerpt": {"type": "string", "description": "Short excerpt of the article (optional)"},
                        "status": {
                            "type": "string", 
                            "description": "Publication status (draft, publish, pending, private)",
                            "enum": ["draft", "publish", "pending", "private"],
                            "default": "draft"
                        },
                        "categories": {
                            "type": "array",
                            "description": "List of category IDs (integers). Use PREPARE_ARTICLE_METADATA to get IDs.",
                            "items": {"type": "integer"}
                        },
                        "tags": {
                            "type": "array",
                            "description": "List of tag IDs (integers). Use PREPARE_ARTICLE_METADATA to get IDs.",
                            "items": {"type": "integer"}
                        },
                        "site_url": {"type": "string", "description": f"WordPress site URL (default: {os.getenv('WP_SITE_URL', '')})"},
                        "username": {"type": "string", "description": f"WordPress username (default: {os.getenv('WP_USERNAME', '')})"},
                        "password": {"type": "string", "description": f"WordPress application password (default: {os.getenv('WP_PASSWORD', '')})"}
                    },
                    "required": ["title", "content"],
                },
            ),
            types.Tool(
                name="PREPARE_ARTICLE_METADATA",
                description="Check for existing categories and tags, create them if they don't exist, and return their IDs",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "categories": {
                            "type": "array",
                            "description": "List of category names (strings) to check or create",
                            "items": {"type": "string"}
                        },
                        "tags": {
                            "type": "array",
                            "description": "List of tag names (strings) to check or create",
                            "items": {"type": "string"}
                        },
                        "site_url": {"type": "string", "description": f"WordPress site URL (default: {os.getenv('WP_SITE_URL', '')})"},
                        "username": {"type": "string", "description": f"WordPress username (default: {os.getenv('WP_USERNAME', '')})"},
                        "password": {"type": "string", "description": f"WordPress application password (default: {os.getenv('WP_PASSWORD', '')})"}
                    },
                    "required": [],
                },
            ),
            types.Tool(
                name="TEST_CONNECTION",
                description="Test connection to WordPress site",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "site_url": {"type": "string", "description": f"WordPress site URL (default: {os.getenv('WP_SITE_URL', '')})"},
                        "username": {"type": "string", "description": f"WordPress username (default: {os.getenv('WP_USERNAME', '')})"},
                        "password": {"type": "string", "description": f"WordPress application password (default: {os.getenv('WP_PASSWORD', '')})"}
                    },
                    "required": [],
                },
            ),
        ]
    
    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
        """Handle tool execution."""
        resources = []
        
        if name == "PUBLISH_ARTICLE":
            try:
                # Extract parameters
                title = arguments.get("title")
                content = arguments.get("content")
                excerpt = arguments.get("excerpt")
                status = arguments.get("status", "draft")
                categories_input = arguments.get("categories", [])
                tags_input = arguments.get("tags", [])
                site_url = arguments.get("site_url", os.getenv("WP_SITE_URL", ""))
                username = arguments.get("username", os.getenv("WP_USERNAME", ""))
                password = arguments.get("password", os.getenv("WP_PASSWORD", ""))
                
                # Create config
                config = WordPressConfig(site_url=site_url, username=username, password=password)
                
                # Get authentication headers
                headers = get_wp_auth(config)
                
                # Upload image if provided
                featured_media_id = None
                if "image" in arguments and arguments["image"]:
                    image_data = arguments["image"]
                    image_name = arguments.get("image_name", "image.jpg")
                    featured_media_id = upload_media_to_wordpress(image_data, image_name, config)
                
                # Create article payload
                article_data = {
                    "title": title,
                    "content": content,
                    "status": status,
                }
                
                if excerpt:
                    article_data["excerpt"] = excerpt
                if categories_input:
                    article_data["categories"] = categories_input
                if tags_input:
                    article_data["tags"] = tags_input
                if featured_media_id:
                    article_data["featured_media"] = featured_media_id
                
                # Publish article
                posts_url = f"{config.site_url}/wp-json/wp/v2/posts"
                response = requests.post(posts_url, headers=headers, json=article_data)
                
                if response.status_code in (201, 200):
                    result = response.json()
                    edit_url = f"{config.site_url}/wp-admin/post.php?post={result.get('id')}&action=edit"
                    
                    resources.append(types.TextContent(
                        type="text",
                        text=f"Article published successfully!\n\nTitle: {title}\nStatus: {result.get('status')}\nID: {result.get('id')}\nURL: {result.get('link')}\nEdit URL: {edit_url}"
                    ))
                else:
                    resources.append(types.TextContent(
                        type="text",
                        text=f"Failed to publish article: {response.text}"
                    ))
                    
            except Exception as e:
                import traceback
                resources.append(types.TextContent(
                    type="text",
                    text=f"Error publishing article: {str(e)}\n\n{traceback.format_exc()}"
                ))
                
        elif name == "PREPARE_ARTICLE_METADATA":
            try:
                # Extract parameters
                categories_input = arguments.get("categories", [])
                tags_input = arguments.get("tags", [])
                site_url = arguments.get("site_url", os.getenv("WP_SITE_URL", ""))
                username = arguments.get("username", os.getenv("WP_USERNAME", ""))
                password = arguments.get("password", os.getenv("WP_PASSWORD", ""))
                
                # Create config
                config = WordPressConfig(site_url=site_url, username=username, password=password)
                
                # Get authentication headers
                headers = get_wp_auth(config)
                
                # Get all categories
                categories_url = f"{config.site_url}/wp-json/wp/v2/categories?per_page=100"
                categories_response = requests.get(categories_url, headers=headers)
                all_categories = categories_response.json() if categories_response.status_code == 200 else []
                
                # Get all tags
                tags_url = f"{config.site_url}/wp-json/wp/v2/tags?per_page=100"
                tags_response = requests.get(tags_url, headers=headers)
                all_tags = tags_response.json() if tags_response.status_code == 200 else []
                
                # Process categories - find or create
                category_ids = []
                for category_item in categories_input:
                    category_id = None
                    for cat in all_categories:
                        if cat["name"].lower() == category_item.lower():
                            category_id = cat["id"]
                            resources.append(types.TextContent(
                                type="text",
                                text=f"Found existing category '{category_item}' with ID {category_id}"
                            ))
                            break
                    
                    if not category_id:
                        # Create new category
                        category_data = {
                            "name": category_item,
                            "slug": category_item.lower().replace(" ", "-")
                        }
                        create_url = f"{config.site_url}/wp-json/wp/v2/categories"
                        create_response = requests.post(create_url, headers=headers, json=category_data)
                        
                        if create_response.status_code == 201:
                            category_id = create_response.json().get("id")
                            resources.append(types.TextContent(
                                type="text",
                                text=f"Created new category '{category_item}' with ID {category_id}"
                            ))
                        else:
                            resources.append(types.TextContent(
                                type="text",
                                text=f"Failed to create category: {create_response.text}"
                            ))
                    
                    if category_id:
                        category_ids.append(category_id)
                
                # Process tags - find or create
                tag_ids = []
                for tag_item in tags_input:
                    tag_id = None
                    for tag in all_tags:
                        if tag["name"].lower() == tag_item.lower():
                            tag_id = tag["id"]
                            resources.append(types.TextContent(
                                type="text",
                                text=f"Found existing tag '{tag_item}' with ID {tag_id}"
                            ))
                            break
                    
                    if not tag_id:
                        # Create new tag
                        tag_data = {
                            "name": tag_item,
                            "slug": tag_item.lower().replace(" ", "-")
                        }
                        create_url = f"{config.site_url}/wp-json/wp/v2/tags"
                        create_response = requests.post(create_url, headers=headers, json=tag_data)
                        
                        if create_response.status_code == 201:
                            tag_id = create_response.json().get("id")
                            resources.append(types.TextContent(
                                type="text",
                                text=f"Created new tag '{tag_item}' with ID {tag_id}"
                            ))
                        else:
                            resources.append(types.TextContent(
                                type="text",
                                text=f"Failed to create tag: {create_response.text}"
                            ))
                    
                    if tag_id:
                        tag_ids.append(tag_id)
                
                resources.append(types.TextContent(
                    type="text",
                    text=f"Categories: {category_ids}\nTags: {tag_ids}"
                ))
            except Exception as e:
                resources.append(types.TextContent(
                    type="text",
                    text=f"Error preparing article metadata: {str(e)}"
                ))
        elif name == "TEST_CONNECTION":
            try:
                # Extract parameters
                site_url = arguments.get("site_url", os.getenv("WP_SITE_URL", ""))
                username = arguments.get("username", os.getenv("WP_USERNAME", ""))
                password = arguments.get("password", os.getenv("WP_PASSWORD", ""))
                
                # Create config
                config = WordPressConfig(site_url=site_url, username=username, password=password)
                
                # Get authentication headers
                headers = get_wp_auth(config)
                
                # Test connection by getting site info
                info_url = f"{config.site_url}/wp-json"
                response = requests.get(info_url, headers=headers)
                
                if response.status_code == 200:
                    resources.append(types.TextContent(
                        type="text",
                        text=f"Connection successful! WordPress site: {response.json().get('name', 'Unknown')}"
                    ))
                else:
                    resources.append(types.TextContent(
                        type="text",
                        text=f"Connection failed: {response.text}"
                    ))
                
            except Exception as e:
                resources.append(types.TextContent(
                    type="text",
                    text=f"Error testing connection: {str(e)}"
                ))
        else:
            resources.append(types.TextContent(
                type="text",
                text=f"Unknown tool: {name}"
            ))
        
        return resources
    
    async def run_mcp_server():
        """Run the MCP server"""
        try:
            print("Starting WordPress MCP server...", file=sys.stderr)
            
            async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
                await server.run(
                    read_stream,
                    write_stream,
                    InitializationOptions(
                        server_name="wordpress-publish",
                        server_version="1.0.0",
                        capabilities=server.get_capabilities(
                            notification_options=NotificationOptions(),
                            experimental_capabilities={},
                        ),
                    ),
                )
        except Exception as e:
            import traceback
            print(f"Error running MCP server: {str(e)}", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            sys.exit(1)
            
except ImportError:
    # MCP library not available, continue with just FastAPI
    print("MCP library not available, running as standalone FastAPI server", file=sys.stderr)
    server = None

if __name__ == "__main__":
    # Check if running as MCP server or standalone FastAPI
    if server and "--mcp" in sys.argv:
        # Run as MCP server
        asyncio.run(run_mcp_server())
    else:
        # Run as standalone FastAPI
        import uvicorn
        uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
