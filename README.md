# sybilla-mcp

A FastMCP server for querying Oracle Cloud Infrastructure (OCI) Logging. This server provides tools for traffic analytics, country-based log searches, and IP-based filtering, making it easy to analyze OCI logs through an MCP-compatible client (like Claude Desktop).

## Prerequisites

- **OCI Authentication (one of the following):**
  - **User Principal (default):** An OCI configuration file (usually at `~/.oci/config`) with valid credentials.
  - **Instance Principal:** The compute instance / container must belong to a Dynamic Group with an IAM policy granting access to the target log resources. No config file needed.
- **uv:** This project uses `uv` for dependency management. If you don't have it, install it via:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

## Installation & Setup

The server uses PEP 723 inline metadata, so `uv` will automatically handle dependencies (`fastmcp`, `oci`) on the first run.

### 1. Configuration

The following environment variables are required for the server to function. These should be set in your MCP client configuration (e.g., `claude_desktop_config.json`).

| Variable | Description | Required |
|----------|-------------|----------|
| `OCI_LOG_ID` | OCID of the specific OCI log to query | Yes |
| `OCI_LOG_GROUP_ID` | OCID of the OCI log group containing the log | Yes |
| `OCI_COMPARTMENT_ID` | OCID of the compartment | Yes |
| `OCI_AUTH_TYPE` | Authentication mode: `user_principal` (default) or `instance_principal` | No |
| `OCI_CONFIG_FILE` | Path to your OCI config (default: `~/.oci/config`). *User principal only.* | No |
| `OCI_CONFIG_PROFILE` | OCI profile name (default: `DEFAULT`). *User principal only.* | No |
| `OCI_REGION` | Override the region specified in your OCI config | No |

### 2. Integration with Claude Desktop

#### User Principal (default – uses `~/.oci/config`)

Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sybilla-mcp": {
      "command": "uv",
      "args": [
        "run", 
        "--script", 
        "/absolute/path/to/sybilla-mcp/sybilla_mcp.py"
      ],
      "env": {
        "OCI_LOG_ID": "ocid1.log.oc1...",
        "OCI_LOG_GROUP_ID": "ocid1.loggroup.oc1...",
        "OCI_COMPARTMENT_ID": "ocid1.compartment.oc1..."
      }
    }
  }
}
```

#### Instance Principal (for OCI Compute / OKE / Cloud Shell)

When running on an OCI instance that belongs to a Dynamic Group with the
appropriate IAM policies, set `OCI_AUTH_TYPE` to `instance_principal`.
No OCI config file or API key is required.

```json
{
  "mcpServers": {
    "sybilla-mcp": {
      "command": "uv",
      "args": [
        "run",
        "--script",
        "/absolute/path/to/sybilla-mcp/sybilla_mcp.py"
      ],
      "env": {
        "OCI_AUTH_TYPE": "instance_principal",
        "OCI_LOG_ID": "ocid1.log.oc1...",
        "OCI_LOG_GROUP_ID": "ocid1.loggroup.oc1...",
        "OCI_COMPARTMENT_ID": "ocid1.compartment.oc1..."
      }
    }
  }
}
```

> **Note:** The compute instance must be in a [Dynamic Group](https://docs.oracle.com/en-us/iaas/Content/Identity/Tasks/callingservicesfrominstances.htm) with a policy like:
> ```
> Allow dynamic-group <group-name> to read log-content in compartment <compartment-name>
> ```

## Exposed Tools

### `get_traffic_analytics`
Returns aggregated traffic analytics from OCI logs.
- **Arguments:**
  - `time_range` (string, default: `"24h"`): How far back to look (e.g., `'1h'`, `'7d'`, `'2w'`).
  - `group_by` (string, default: `"country"`): Dimension to group by (`'country'`, `'ip'`, `'status_code'`, or `'path'`).
  - `limit` (integer, default: `1000`): Maximum number of raw log entries to consider (max 1000).

### `search_logs_by_country`
Search OCI logs filtered by a specific country.
- **Arguments:**
  - `country` (string): Country name or two-letter ISO code (e.g., `'US'`, `'Germany'`).
  - `time_range` (string, default: `"24h"`): Time range to search.
  - `limit` (integer, default: `100`): Maximum results.

### `search_logs_by_countries`
Search OCI logs for multiple countries at once.
- **Arguments:**
  - `countries` (list of strings): List of country names or ISO codes (e.g., `['US', 'DE', 'FR']`).
  - `time_range` (string, default: `"24h"`): Time range to search.
  - `limit` (integer, default: `100`): Maximum results.

### `search_logs_by_ip`
Search OCI logs by a specific IP address or CIDR range.
- **Arguments:**
  - `ip_address` (string, optional): Exact IP to filter on (e.g., `'1.2.3.4'`).
  - `ip_range` (string, optional): CIDR range (e.g., `'10.0.0.0/8'`). Note: prefix-based matching is applied.
  - `time_range` (string, default: `"24h"`): Time range to search.
  - `limit` (integer, default: `100`): Maximum results.

### `search_logs_raw`
Run a free-form OCI Logging search query using SQL-like syntax.
- **Arguments:**
  - `query_filter` (string): OCI Logging query fragment (e.g., `"| where data.status = '500' | sort by datetime desc"`).
  - `time_range` (string, default: `"24h"`): Time range to search.
  - `limit` (integer, default: `100`): Maximum results.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
