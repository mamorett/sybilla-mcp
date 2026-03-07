# sybilla-mcp

A FastMCP server for querying Oracle Cloud Infrastructure (OCI) Logging. Provides tools for traffic analytics, country-based log searches, and IP-based filtering — usable directly from any MCP-compatible client (like Claude Desktop).

## Installation

### Run directly with `uvx` (recommended)

No cloning needed. `uvx` installs and runs the server in one step:

```bash
uvx --from git+https://github.com/mamorett/sybilla-mcp sybilla-mcp
```

### Install as a persistent tool

```bash
uv tool install git+https://github.com/mamorett/sybilla-mcp
sybilla-mcp
```

### Run from a local clone

```bash
git clone https://github.com/mamorett/sybilla-mcp
cd sybilla-mcp
uv run sybilla_mcp.py
```

## Prerequisites

**OCI Authentication — one of the following:**

- **User Principal (default):** An OCI configuration file at `~/.oci/config` with valid credentials.
- **Instance Principal:** The compute instance / container must belong to a Dynamic Group with an IAM policy granting access to the target log resources. No config file needed.

## Configuration

The following environment variables must be set in your MCP client configuration (e.g. `claude_desktop_config.json`). **Do not use a `.env` file.**

| Variable | Required | Description |
|---|---|---|
| `OCI_LOG_ID` | ✅ | OCID of the specific OCI log to query |
| `OCI_LOG_GROUP_ID` | ✅ | OCID of the OCI log group |
| `OCI_COMPARTMENT_ID` | ✅ | OCID of the compartment |
| `OCI_AUTH_TYPE` | — | `user_principal` (default) or `instance_principal` |
| `OCI_CONFIG_FILE` | — | Path to OCI config (default: `~/.oci/config`). *User principal only.* |
| `OCI_CONFIG_PROFILE` | — | OCI profile name (default: `DEFAULT`). *User principal only.* |
| `OCI_REGION` | — | Override the region in your OCI config |

## Integration with Claude Desktop

Add one of the following blocks to your `claude_desktop_config.json`.

### User Principal (default — uses `~/.oci/config`)

```json
{
  "mcpServers": {
    "sybilla-mcp": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/mamorett/sybilla-mcp",
        "sybilla-mcp"
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

### Instance Principal (OCI Compute / OKE / Cloud Shell)

```json
{
  "mcpServers": {
    "sybilla-mcp": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/mamorett/sybilla-mcp",
        "sybilla-mcp"
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

> **Note:** The instance must belong to a [Dynamic Group](https://docs.oracle.com/en-us/iaas/Content/Identity/Tasks/callingservicesfrominstances.htm) with a policy like:
> ```
> Allow dynamic-group <group-name> to read log-content in compartment <compartment-name>
> ```

## Exposed Tools

### `get_traffic_analytics`
Returns aggregated traffic analytics from OCI logs.
- `time_range` *(default: `"24h"`)* — How far back to look, e.g. `'1h'`, `'7d'`, `'2w'`.
- `group_by` *(default: `"country"`)* — Dimension: `'country'`, `'ip'`, `'status_code'`, or `'path'`.
- `limit` *(default: `1000`)* — Max raw log entries to consider (hard cap: 1000).

### `search_logs_by_country`
Filters logs by a single country.
- `country` — Name or two-letter ISO code, e.g. `'US'`, `'Germany'`.
- `time_range` *(default: `"24h"`)*
- `limit` *(default: `100`)*

### `search_logs_by_countries`
Filters logs for multiple countries at once.
- `countries` — List of names or ISO codes, e.g. `['US', 'DE', 'FR']`.
- `time_range` *(default: `"24h"`)*
- `limit` *(default: `100`)*

### `search_logs_by_ip`
Filters logs by an exact IP address or CIDR range.
- `ip_address` *(optional)* — Exact IP, e.g. `'1.2.3.4'`.
- `ip_range` *(optional)* — CIDR range, e.g. `'10.0.0.0/8'` (prefix-based matching).
- `time_range` *(default: `"24h"`)*
- `limit` *(default: `100`)*

### `search_logs_raw`
Runs a free-form OCI Logging query (SQL-like syntax).
- `query_filter` — Query fragment, e.g. `"| where data.status = '500' | sort by datetime desc"`.
- `time_range` *(default: `"24h"`)*
- `limit` *(default: `100`)*

## License

MIT — see [LICENSE](LICENSE).
