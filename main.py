import os
import base64
import json
import asyncio
import sys
from typing import List, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
from dotenv import load_dotenv

# Load environment variables
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
    categories: str = Form("[]"),  # JSON string of category names
    tags: str = Form("[]"),  # JSON string of tag names
    image: Optional[UploadFile] = File(None),
    site_url: str = Form(os.getenv("WP_SITE_URL", "")),
    username: str = Form(os.getenv("WP_USERNAME", "")),
    password: str = Form(os.getenv("WP_PASSWORD", "")),
):
    """
    Publish an article to WordPress with optional image, categories, and tags
    """
    # Parse JSON strings
    try:
        categories_list = json.loads(categories)
        tags_list = json.loads(tags)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format for categories or tags")
    
    # Create WordPress config
    config = WordPressConfig(site_url=site_url, username=username, password=password)
    
    # Set up authentication headers
    headers = get_wp_auth(config)
    headers["Content-Type"] = "application/json"
    
    # STEP 1: Get all existing categories from WordPress
    all_categories_url = f"{config.site_url}/wp-json/wp/v2/categories?per_page=100"
    all_categories_response = requests.get(all_categories_url, headers=headers)
    
    all_categories = []
    if all_categories_response.status_code == 200:
        all_categories = all_categories_response.json()
    else:
        raise HTTPException(status_code=all_categories_response.status_code, 
                           detail=f"Failed to fetch categories: {all_categories_response.text}")
    
    # STEP 2: Get all existing tags from WordPress
    all_tags_url = f"{config.site_url}/wp-json/wp/v2/tags?per_page=100"
    all_tags_response = requests.get(all_tags_url, headers=headers)
    
    all_tags = []
    if all_tags_response.status_code == 200:
        all_tags = all_tags_response.json()
    else:
        raise HTTPException(status_code=all_tags_response.status_code, 
                           detail=f"Failed to fetch tags: {all_tags_response.text}")
    
    # STEP 3: Process categories - find or create
    category_ids = []
    for category_name in categories_list:
        if category_name and category_name.strip():  # Skip empty category names
            try:
                # First check if category exists in all categories
                category_id = None
                for cat in all_categories:
                    if cat["name"].lower() == category_name.lower():
                        category_id = cat["id"]
                        break
                
                # If not found, try search endpoint
                if not category_id:
                    search_url = f"{config.site_url}/wp-json/wp/v2/categories?search={category_name}"
                    search_response = requests.get(search_url, headers=headers)
                    
                    if search_response.status_code == 200:
                        search_results = search_response.json()
                        
                        # Look for exact match (case insensitive)
                        for cat in search_results:
                            if cat["name"].lower() == category_name.lower():
                                category_id = cat["id"]
                                break
                
                # If still not found, create new category
                if not category_id:
                    category_data = {
                        "name": category_name,
                        "slug": category_name.lower().replace(" ", "-"),
                        "description": f"Category for {category_name}"
                    }
                    create_url = f"{config.site_url}/wp-json/wp/v2/categories"
                    create_response = requests.post(create_url, headers=headers, json=category_data)
                    
                    if create_response.status_code != 201:
                        raise HTTPException(status_code=create_response.status_code, 
                                          detail=f"Failed to create category: {create_response.text}")
                    
                    category_id = create_response.json().get("id")
                
                # Add category ID to list
                if category_id:
                    category_ids.append(category_id)
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error processing category {category_name}: {str(e)}")
    
    # STEP 4: Process tags - find or create
    tag_ids = []
    for tag_name in tags_list:
        if tag_name and tag_name.strip():  # Skip empty tag names
            try:
                # First check if tag exists in all tags
                tag_id = None
                for tag in all_tags:
                    if tag["name"].lower() == tag_name.lower():
                        tag_id = tag["id"]
                        break
                
                # If not found, try search endpoint
                if not tag_id:
                    search_url = f"{config.site_url}/wp-json/wp/v2/tags?search={tag_name}"
                    search_response = requests.get(search_url, headers=headers)
                    
                    if search_response.status_code == 200:
                        search_results = search_response.json()
                        
                        # Look for exact match (case insensitive)
                        for tag in search_results:
                            if tag["name"].lower() == tag_name.lower():
                                tag_id = tag["id"]
                                break
                
                # If still not found, create new tag
                if not tag_id:
                    tag_data = {
                        "name": tag_name,
                        "slug": tag_name.lower().replace(" ", "-")
                    }
                    create_url = f"{config.site_url}/wp-json/wp/v2/tags"
                    create_response = requests.post(create_url, headers=headers, json=tag_data)
                    
                    if create_response.status_code != 201:
                        raise HTTPException(status_code=create_response.status_code, 
                                          detail=f"Failed to create tag: {create_response.text}")
                    
                    tag_id = create_response.json().get("id")
                
                # Add tag ID to list
                if tag_id:
                    tag_ids.append(tag_id)
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error processing tag {tag_name}: {str(e)}")
    
    # STEP 5: Upload image if provided
    featured_media_id = None
    if image:
        image_data = await image.read()
        featured_media_id = upload_media_to_wordpress(image_data, image.filename, config)
    
    # STEP 6: Create article payload WITH the category and tag IDs we obtained
    article_data = {
        "title": title,
        "content": content,
        "status": status,
    }
    
    if excerpt:
        article_data["excerpt"] = excerpt
    if category_ids:
        article_data["categories"] = category_ids
    if tag_ids:
        article_data["tags"] = tag_ids
    if featured_media_id:
        article_data["featured_media"] = featured_media_id
    
    # STEP 7: Publish article with all data in a single request
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
                            "description": "List of category IDs to assign to the article",
                            "items": {"type": "integer"}
                        },
                        "tags": {
                            "type": "array",
                            "description": "List of tag IDs to assign to the article",
                            "items": {"type": "integer"}
                        },
                        "site_url": {"type": "string", "description": "WordPress site URL"},
                        "username": {"type": "string", "description": "WordPress username"},
                        "password": {"type": "string", "description": "WordPress application password"}
                    },
                    "required": ["title", "content", "site_url", "username", "password"],
                },
            ),
            types.Tool(
                name="TEST_CONNECTION",
                description="Test connection to WordPress site",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "site_url": {"type": "string", "description": "WordPress site URL"},
                        "username": {"type": "string", "description": "WordPress username"},
                        "password": {"type": "string", "description": "WordPress application password"}
                    },
                    "required": ["site_url", "username", "password"],
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
                categories = arguments.get("categories", [])
                tags = arguments.get("tags", [])
                site_url = arguments.get("site_url")
                username = arguments.get("username")
                password = arguments.get("password")
                
                # Create config
                config = WordPressConfig(site_url=site_url, username=username, password=password)
                
                # Get authentication headers
                headers = get_wp_auth(config)
                
                # Create article payload
                article_data = {
                    "title": title,
                    "content": content,
                    "status": status,
                }
                
                if excerpt:
                    article_data["excerpt"] = excerpt
                if categories:
                    article_data["categories"] = categories
                if tags:
                    article_data["tags"] = tags
                
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
                resources.append(types.TextContent(
                    type="text",
                    text=f"Error publishing article: {str(e)}"
                ))
                
        elif name == "TEST_CONNECTION":
            try:
                # Extract parameters
                site_url = arguments.get("site_url")
                username = arguments.get("username")
                password = arguments.get("password")
                
                # Create config
                config = WordPressConfig(site_url=site_url, username=username, password=password)
                
                # Test connection
                headers = get_wp_auth(config)
                url = f"{config.site_url}/wp-json/wp/v2/users/me"
                
                response = requests.get(url, headers=headers)
                
                if response.status_code == 200:
                    user_data = response.json()
                    resources.append(types.TextContent(
                        type="text",
                        text=f"Connection successful!\n\nSite: {config.site_url}\nUser: {user_data.get('name')}\nRole: {', '.join(user_data.get('roles', []))}"
                    ))
                else:
                    resources.append(types.TextContent(
                        type="text",
                        text=f"Connection failed: {response.status_code} - {response.text}"
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
