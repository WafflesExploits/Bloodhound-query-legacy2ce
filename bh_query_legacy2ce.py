import json
import requests
import time
import argparse
import uuid

# Define colors using ANSI escape codes
red = "\033[31m"
light_blue = "\033[0;34m"
light_green = "\033[32m"
cyan = "\033[36m"
yellow = "\033[33m"
reset = "\033[0m"  # Reset color

# Constants
MAX_REQUESTS_PER_SECOND = 55  # Rate limit: maximum requests allowed per second - Bloodhound blocks your requests if you exceed this.
DELAY_BETWEEN_REQUESTS = 1 / MAX_REQUESTS_PER_SECOND  # Delay between requests in seconds


def parse_arguments():
    """
    Parse command-line arguments for the script.

    Returns:
        argparse.Namespace: Parsed arguments (input file, --convert-only flag, --upload-only flag, --output-file, JWT token, API URL).
    """
    usage_example = """
\nUsage:
    # Convert Custom Queries and Upload via BloodHound CE API
    python upload_bloodhound_queries.py --input-file bloodhound_legacy_customqueries.json --jwt-token "eyJ0..."

    # Convert Custom Queries and Save in an Output File for Later Use
    python upload_bloodhound_queries.py --input-file bloodhound_legacy_customqueries.json --convert-only --output-file "new_format_custom_queries.json"

    # Upload Pre-Converted Custom Queries
    python upload_bloodhound_queries.py --upload-only --input-file converted_custom_queries.json --jwt-token "eyJ0..."
"""
    
    parser = argparse.ArgumentParser(
        description="A tool to convert custom queries from Legacy BloodHound to BloodHound CE format, with the option to directly upload them to the API or save them to a file for later use. You can also upload pre-converted queries.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(usage_example)
    )
    parser.add_argument("--input-file", required=True, help="Path to the input JSON file containing custom queries or converted queries.")
    parser.add_argument(
        "--convert-only",
        action="store_true",
        help="If specified, the script only performs conversion of queries without uploading to the API."
    )
    parser.add_argument(
        "--upload-only",
        action="store_true",
        help="If specified, the script uploads pre-converted queries without performing conversion."
    )
    parser.add_argument(
        "--output-file",
        default="converted_queries.json",
        help="Path to save the converted queries (only used with --convert-only). Defaults to 'converted_queries.json'."
    )
    parser.add_argument("--jwt-token", help="JWT token for authenticating API requests (required for uploading).")
    parser.add_argument(
        "--api-url",
        default="http://localhost:8080/api/v2/saved-queries",
        help="API endpoint URL. Defaults to http://localhost:8080/api/v2/saved-queries."
    )
    return parser.parse_args()


def load_query(input_file):
    """
    Load queries from the input JSON file.

    Args:
        input_file (str): Path to the input file.

    Returns:
        dict or list: The JSON object or list loaded from the file if successful, None otherwise.
    """
    try:
        with open(input_file, "r") as file:
            data = json.load(file)  # Load the JSON data from the file
        return data
    except FileNotFoundError:
        print(f"{red}Error: The file '{input_file}' was not found. Please check the file path.{reset}")
        return
    except json.JSONDecodeError:
        print(f"{red}Error: Failed to decode JSON from the file '{input_file}'. Ensure it contains a valid JSON structure.{reset}")
        return


def convert_legacy_queries(legacy_queries):
    """
    Convert queries from the Legacy BloodHound format to the BloodHound CE format.

    Args:
        legacy_queries (dict): The original JSON data in Legacy BloodHound format.

    Returns:
        list: A list of converted queries ready for upload in BloodHound CE format.
    """
    try:
        converted = []
        for query in legacy_queries.get("queries", []):  # Iterate over "queries" list in Legacy JSON object

            query_name = query.get("name", "").strip()  # Get the 'name', or use an empty string as the default
            query_data = query.get("queryList", [{}])[0].get("query")  # Safely retrieve the query data

            # Skip invalid or empty queries
            if not query_data:
                print(f"{yellow}Query '{query_name or 'Unnamed query'}' skipped since its 'query' field was null or empty.{reset}")
                continue

            if not query_name:
                unique_id = uuid.uuid4()  # Generate a unique identifier
                query_name = f"Unnamed query {unique_id}"
                print(f"{cyan}Query with empty name, new name assigned: {query_name}{reset}")
            # Extract required fields
            converted_query = {
                "name": query_name,  # Query name
                "query": query_data  # Cypher query
            }

            # Add category if it exists, otherwise set to None (or omit this key entirely, if desired)
            converted_query["category"] = query.get("category", None)

            # Add the converted query to the list
            converted.append(converted_query)

        return converted
    except KeyError as e:
        # Handles any missing keys in the input JSON
        print(f"{red}Error: Missing expected key '{e}' in the legacy query format. Ensure the input file is valid.{reset}")
        return []


def save_converted_queries(queries, output_file):
    """
    Save the converted queries to a specified output file in JSON format.

    Args:
        queries (list): List of converted queries.
        output_file (str): File path where the queries should be saved.
    """
    try:
        with open(output_file, "w") as file:
            json.dump(queries, file, indent=4)
        print(f"{light_green}Converted queries have been saved to '{output_file}'.{reset}")
    except Exception as e:
        print(f"{red}Error: Could not save converted queries to the file '{output_file}'.{reset}")
        print(f"{red}Error details: {e}{reset}")


def upload_query(api_url, jwt_token, query, count):
    """
    Upload a single query to the specified API endpoint.

    Args:
        api_url (str): API endpoint URL.
        jwt_token (str): JWT token for authentication.
        query (dict): The query object to be uploaded.
        count (int): The query count in the current batch.

    Returns:
        bool: True if the query was uploaded successfully, False otherwise.
    """
    try:
        response = requests.post(
            url=api_url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {jwt_token}"
            },
            json=query
        )

        if response.status_code == 200 or response.status_code == 201:
            print(f"{light_green}{count}. Query uploaded successfully: {query.get('name', 'Unnamed query')}{reset}\n")
            return True
        else:
            print(f"\n{red}{count}. Failed to upload query: {query.get('name', 'Unnamed query')}{reset}")
            print(f"{red}HTTP {response.status_code} - {response.text}{reset}\n")
            return False
    except Exception as e:
        print(f"\n{red}{count}. An error occurred while uploading query: {query.get('name', 'Unnamed query')}{reset}")
        print(f"{red}Error: {e}{reset}\n")
        return False


def upload_queries(api_url, jwt_token, queries):
    """
    Upload all converted queries to the API, respecting the rate limit.

    Args:
        api_url (str): API endpoint URL.
        jwt_token (str): JWT token for authentication.
        queries (list): List of query objects to be uploaded.
    """
    for count, query in enumerate(queries, start=1):
        # Upload each query and apply rate limiting
        success = upload_query(api_url, jwt_token, query, count)

        # Enforce rate limiting through delay between each request
        time.sleep(DELAY_BETWEEN_REQUESTS)


def main():
    """
    Main function to manage the following:
    - Parse command-line arguments
    - Load queries (legacy or pre-converted)
    - Optionally convert the queries
    - Upload the queries if specified
    """
    # Step 1: Parse command-line arguments
    args = parse_arguments()
    input_file = args.input_file
    convert_only = args.convert_only
    upload_only = args.upload_only
    output_file = args.output_file
    jwt_token = args.jwt_token
    api_url = args.api_url

    # Step 2: Load queries from the input file
    queries = load_query(input_file)
    if not queries:
        return  # Exit if queries couldn't be loaded

    # If --upload-only is specified, directly upload pre-converted queries
    if upload_only:
        if not jwt_token:
            print(f"{red}Error: JWT token is required for uploading queries in --upload-only mode.{reset}")
            return

        print(f"{cyan}Starting to upload pre-converted queries to the API...{reset}\n")
        upload_queries(api_url, jwt_token, queries)
        print(f"{light_blue}All queries uploaded.{reset}")
        return

    # Step 3: Convert legacy queries to BloodHound CE format
    print(f"{cyan}Converting queries from Legacy BloodHound format to BloodHound CE format...{reset}")
    converted_queries = convert_legacy_queries(queries)

    if not converted_queries:
        print(f"{red}Error: No queries found after conversion or conversion failed. Please check the input file format.{reset}")
        return

    # If the --convert-only flag is provided, save converted queries to the specified output file
    if convert_only:
        save_converted_queries(converted_queries, output_file)
        return

    # Step 4: Upload converted queries with rate limiting
    if not jwt_token:
        print(f"{red}Error: JWT token is required for uploading queries. Use --convert-only to skip uploading.{reset}")
        return

    print(f"{cyan}Starting to upload {len(converted_queries)} queries to the API...{reset}\n")
    upload_queries(api_url, jwt_token, converted_queries)
    print(f"{light_blue}All queries uploaded.{reset}")


if __name__ == "__main__":
    main()
