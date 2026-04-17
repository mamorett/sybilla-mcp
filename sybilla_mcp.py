#!/usr/bin/env python3
"""
FastMCP server for Oracle Cloud Infrastructure (OCI) Logging.

Authentication:
  Supports two authentication modes, controlled by OCI_AUTH_TYPE:

  1. user_principal (default)
     Uses OCI config file (~/.oci/config) with DEFAULT profile
     (or OCI_CONFIG_PROFILE env var).

  2. instance_principal
     Uses the instance's own identity via Instance Principal.
     No config file is needed; the instance must be in a Dynamic Group
     with an appropriate IAM policy.  Ideal for running on OCI Compute,
     OKE (Kubernetes), or Cloud Shell.

Environment variables (set via MCP JSON config, NOT .env):
  Required:
    OCI_LOG_ID          - OCID of the log to query
    OCI_LOG_GROUP_ID    - OCID of the log group
    OCI_COMPARTMENT_ID  - OCID of the compartment

  Optional:
    OCI_AUTH_TYPE       - 'user_principal' (default) or 'instance_principal'
    OCI_CONFIG_FILE     - Path to OCI config file (default: ~/.oci/config)
                          (user_principal only)
    OCI_CONFIG_PROFILE  - OCI config profile name (default: DEFAULT)
                          (user_principal only)
    OCI_REGION          - Override region from config file
"""

import os
import json
import logging
import socket
from datetime import datetime, timedelta, timezone
from typing import Optional

import oci
from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastMCP app
# ---------------------------------------------------------------------------
mcp = FastMCP(
    name="oci-logs",
    instructions=(
        "MCP server for querying OCI Logging. "
        "Supports traffic analytics, country-based searches, and IP-based searches."
    ),
)

# ---------------------------------------------------------------------------
# OCI configuration (read once at import time)
# ---------------------------------------------------------------------------
_OCI_AUTH_TYPE       = os.environ.get("OCI_AUTH_TYPE", "user_principal").lower()
_OCI_REGION_OVERRIDE = os.environ.get("OCI_REGION")          # optional

_VALID_AUTH_TYPES = {"user_principal", "instance_principal"}
if _OCI_AUTH_TYPE not in _VALID_AUTH_TYPES:
    raise ValueError(
        f"OCI_AUTH_TYPE must be one of {_VALID_AUTH_TYPES}, got '{_OCI_AUTH_TYPE}'"
    )

# Config-file settings are only relevant for user_principal auth.
# Avoid reading them (and referencing the default config path) when using
# instance_principal, since no config file is expected to exist.
if _OCI_AUTH_TYPE == "user_principal":
    _OCI_CONFIG_FILE    = os.environ.get("OCI_CONFIG_FILE", oci.config.DEFAULT_LOCATION)
    _OCI_CONFIG_PROFILE = os.environ.get("OCI_CONFIG_PROFILE", oci.config.DEFAULT_PROFILE)

# Required identifiers – must be provided via MCP JSON env block
_LOG_ID          = os.environ["OCI_LOG_ID"]
_LOG_GROUP_ID    = os.environ["OCI_LOG_GROUP_ID"]
_COMPARTMENT_ID  = os.environ["OCI_COMPARTMENT_ID"]


def _get_oci_config() -> tuple[dict, Optional[oci.auth.signers.InstancePrincipalsSecurityTokenSigner]]:
    """Return (config_dict, signer_or_None) for the configured auth type."""
    if _OCI_AUTH_TYPE == "instance_principal":
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        config: dict = {}
        if _OCI_REGION_OVERRIDE:
            config["region"] = _OCI_REGION_OVERRIDE
        logger.info("Using Instance Principal authentication")
        return config, signer

    # --- user_principal (default) ---
    config = oci.config.from_file(
        file_location=_OCI_CONFIG_FILE,
        profile_name=_OCI_CONFIG_PROFILE,
    )
    if _OCI_REGION_OVERRIDE:
        config["region"] = _OCI_REGION_OVERRIDE
    oci.config.validate_config(config)
    logger.info("Using User Principal authentication (config file)")
    return config, None


def _get_logging_client() -> oci.loggingsearch.LogSearchClient:
    """Build an authenticated OCI LogSearchClient."""
    config, signer = _get_oci_config()
    if signer:
        return oci.loggingsearch.LogSearchClient(config, signer=signer)
    return oci.loggingsearch.LogSearchClient(config)


def _time_range_to_dates(time_range: str) -> tuple[str, str]:
    """Convert a human-friendly time range string to ISO-8601 start/end strings."""
    now = datetime.now(timezone.utc)
    units = {"h": "hours", "d": "days", "w": "weeks"}
    unit = time_range[-1]
    value = int(time_range[:-1])
    if unit not in units:
        raise ValueError(f"Unsupported time range unit '{unit}'. Use h/d/w, e.g. '24h', '7d'.")
    delta = timedelta(**{units[unit]: value})
    start = (now - delta).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end   = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return start, end


def _execute_search(query: str, time_range: str, limit: int) -> list[dict]:
    """Run a log search query and return a list of log-entry dicts."""
    client = _get_logging_client()
    start, end = _time_range_to_dates(time_range)

    details = oci.loggingsearch.models.SearchLogsDetails(
        time_start=start,
        time_end=end,
        search_query=query,
        is_return_field_info=False,
    )

    response = client.search_logs(
        search_logs_details=details,
        limit=min(limit, 1000),
    )

    results = response.data.results or []
    return [r.data if isinstance(r.data, dict) else json.loads(str(r.data)) for r in results]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_traffic_analytics(
    time_range: str = "24h",
    group_by: str = "country",
    limit: int = 1000,
) -> dict:
    """
    Return aggregated traffic analytics from OCI logs.

    Args:
        time_range: How far back to look, e.g. '24h', '7d', '2w'.
        group_by:   Dimension to group by – 'country', 'ip', 'status_code', or 'path'.
        limit:      Maximum number of raw log entries to consider (max 1000).

    Returns:
        A dict with a 'summary' key containing grouped counts and a 'total' key.
    """
    valid_groups = {"country", "ip", "status_code", "path"}
    if group_by not in valid_groups:
        return {"error": f"group_by must be one of {valid_groups}"}

    # Map logical group to OCI log field name
    field_map = {
        "country":     "data.country",
        "ip":          "data.clientip",
        "status_code": "data.status",
        "path":        "data.request",
    }
    field = field_map[group_by]

    query = (
        f"search \"{_COMPARTMENT_ID}/{_LOG_GROUP_ID}/{_LOG_ID}\" "
        f"| summarize count(*) as count by {field} "
        f"| sort by count desc"
    )

    try:
        entries = _execute_search(query, time_range, limit)
        return {
            "group_by": group_by,
            "time_range": time_range,
            "total": len(entries),
            "summary": entries,
        }
    except Exception as exc:
        logger.exception("get_traffic_analytics failed")
        return {"error": str(exc)}


@mcp.tool()
def search_logs_by_country(
    country: str,
    time_range: str = "24h",
    limit: int = 100,
) -> dict:
    """
    Search OCI logs filtered by a specific country.

    Args:
        country:    Country name or two-letter ISO code (e.g. 'US', 'Germany').
        time_range: How far back to look, e.g. '24h', '7d'.
        limit:      Maximum number of entries to return.

    Returns:
        A dict with 'country', 'total', and 'entries' keys.
    """
    query = (
        f"search \"{_COMPARTMENT_ID}/{_LOG_GROUP_ID}/{_LOG_ID}\" "
        f"| where data.country = '{country}' "
        f"| sort by datetime desc"
    )

    try:
        entries = _execute_search(query, time_range, limit)
        return {"country": country, "time_range": time_range, "total": len(entries), "entries": entries}
    except Exception as exc:
        logger.exception("search_logs_by_country failed")
        return {"error": str(exc)}


@mcp.tool()
def search_logs_by_countries(
    countries: list[str],
    time_range: str = "24h",
    limit: int = 100,
) -> dict:
    """
    Search OCI logs for multiple countries at once.

    Args:
        countries:  List of country names or ISO codes, e.g. ['US', 'DE', 'FR'].
        time_range: How far back to look.
        limit:      Maximum number of entries to return.

    Returns:
        A dict keyed by country with nested entry lists, plus a 'total' count.
    """
    quoted = ", ".join(f"'{c}'" for c in countries)
    query = (
        f"search \"{_COMPARTMENT_ID}/{_LOG_GROUP_ID}/{_LOG_ID}\" "
        f"| where data.country in ({quoted}) "
        f"| sort by datetime desc"
    )

    try:
        entries = _execute_search(query, time_range, limit)

        # Group by country for a cleaner response
        grouped: dict[str, list] = {}
        for entry in entries:
            c = entry.get("data", {}).get("country", "unknown")
            grouped.setdefault(c, []).append(entry)

        return {
            "countries": countries,
            "time_range": time_range,
            "total": len(entries),
            "by_country": grouped,
        }
    except Exception as exc:
        logger.exception("search_logs_by_countries failed")
        return {"error": str(exc)}


@mcp.tool()
def search_logs_by_ip(
    ip_address: Optional[str] = None,
    ip_range: Optional[str] = None,
    time_range: str = "24h",
    limit: int = 100,
) -> dict:
    """
    Search OCI logs by a specific IP address or CIDR range.

    Args:
        ip_address: Exact IP to filter on, e.g. '1.2.3.4'.
        ip_range:   CIDR range to filter on, e.g. '10.0.0.0/8'.
                    (Only prefix-based matching is applied client-side.)
        time_range: How far back to look.
        limit:      Maximum number of entries to return.

    Returns:
        A dict with 'total' and 'entries' keys.
    """
    if not ip_address and not ip_range:
        return {"error": "Provide either ip_address or ip_range."}

    if ip_address:
        where_clause = f"data.clientip = '{ip_address}'"
        label = ip_address
    else:
        # OCI search SQL doesn't natively support CIDR; filter by prefix
        prefix = ip_range.split("/")[0].rsplit(".", 1)[0]  # e.g. '10.0.0'
        where_clause = f"data.clientip like '{prefix}.%'"
        label = ip_range

    query = (
        f"search \"{_COMPARTMENT_ID}/{_LOG_GROUP_ID}/{_LOG_ID}\" "
        f"| where {where_clause} "
        f"| sort by datetime desc"
    )

    try:
        entries = _execute_search(query, time_range, limit)
        return {
            "ip_filter": label,
            "time_range": time_range,
            "total": len(entries),
            "entries": entries,
        }
    except Exception as exc:
        logger.exception("search_logs_by_ip failed")
        return {"error": str(exc)}


@mcp.tool()
def search_logs_raw(
    query_filter: str,
    time_range: str = "24h",
    limit: int = 100,
) -> dict:
    """
    Run a free-form OCI Logging search query (SQL-like syntax).

    Args:
        query_filter: OCI Logging query fragment appended after the base search,
                      e.g. "| where data.status = '500' | sort by datetime desc".
        time_range:   How far back to look.
        limit:        Maximum number of entries to return.

    Returns:
        A dict with 'total' and 'entries' keys.
    """
    query = (
        f"search \"{_COMPARTMENT_ID}/{_LOG_GROUP_ID}/{_LOG_ID}\" "
        f"{query_filter}"
    )

    try:
        entries = _execute_search(query, time_range, limit)
        return {"time_range": time_range, "total": len(entries), "entries": entries}
    except Exception as exc:
        logger.exception("search_logs_raw failed")
        return {"error": str(exc)}


@mcp.tool()
def list_sensors(
    time_range: str = "24h",
    limit: int = 1000,
) -> dict:
    """
    Return all unique sensor names found in the logs within a time window.

    Args:
        time_range: How far back to look, e.g. '24h', '7d', '2w'.
        limit:      Maximum number of raw log entries to consider (max 1000).

    Returns:
        A dict with 'sensors' (list of {name, count}), 'total_sensors',
        'time_range', and 'total_entries'.
    """
    query = (
        f"search \"{_COMPARTMENT_ID}/{_LOG_GROUP_ID}/{_LOG_ID}\" "
        f"| summarize count() by data.Sensor "
        f"| sort by count desc"
    )

    try:
        entries = _execute_search(query, time_range, limit)

        sensors = []
        for entry in entries:
            sensor_name = entry.get("data.Sensor", "")
            count = entry.get("count", 0)
            sensors.append({"name": sensor_name, "count": count})

        return {
            "sensors": sensors,
            "total_sensors": len(sensors),
            "time_range": time_range,
            "total_entries": len(entries),
        }
    except Exception as exc:
        logger.exception("list_sensors failed")
        return {"error": str(exc)}


@mcp.tool()
def search_logs_by_sensor(
    sensor: str,
    time_range: str = "24h",
    limit: int = 100,
) -> dict:
    """
    Search OCI logs filtered by a specific sensor name.

    Args:
        sensor:     Sensor name to filter on, e.g. 'ssh_22', 'cowrie'.
        time_range: How far back to look, e.g. '24h', '7d'.
        limit:      Maximum number of entries to return.

    Returns:
        A dict with 'sensor', 'time_range', 'total', and 'entries' keys.
    """
    query = (
        f"search \"{_COMPARTMENT_ID}/{_LOG_GROUP_ID}/{_LOG_ID}\" "
        f"| where data.sensor = '{sensor}' "
        f"| sort by datetime desc"
    )

    try:
        entries = _execute_search(query, time_range, limit)
        return {"sensor": sensor, "time_range": time_range, "total": len(entries), "entries": entries}
    except Exception as exc:
        logger.exception("search_logs_by_sensor failed")
        return {"error": str(exc)}


@mcp.tool()
def resolve_ocid(ocid: str) -> dict:
    """
    Resolve an OCI resource OCID to its human-readable display name.

    Supports:
      - Compute instances  (ocid1.instance.oc1...)
      - Load balancers     (ocid1.loadbalancer.oc1...)

    Args:
        ocid: The full OCID of the resource to look up.

    Returns:
        A dict with 'ocid', 'resource_type', and 'display_name' keys,
        or an 'error' key on failure.
    """
    if not ocid.startswith("ocid1."):
        return {"error": f"'{ocid}' does not look like a valid OCID."}

    # Derive resource type from the second segment of the OCID
    # e.g. 'ocid1.instance.oc1...' -> 'instance'
    try:
        resource_type = ocid.split(".")[1].lower()
    except IndexError:
        return {"error": "Unable to parse resource type from OCID."}

    try:
        config, signer = _get_oci_config()
        kwargs = {"signer": signer} if signer else {}

        if resource_type == "instance":
            client = oci.core.ComputeClient(config, **kwargs)
            instance = client.get_instance(ocid).data
            return {
                "ocid": ocid,
                "resource_type": "instance",
                "display_name": instance.display_name,
                "lifecycle_state": instance.lifecycle_state,
                "shape": instance.shape,
                "availability_domain": instance.availability_domain,
            }

        if resource_type == "loadbalancer":
            client = oci.load_balancer.LoadBalancerClient(config, **kwargs)
            lb = client.get_load_balancer(ocid).data
            return {
                "ocid": ocid,
                "resource_type": "load_balancer",
                "display_name": lb.display_name,
                "lifecycle_state": lb.lifecycle_state,
                "shape_name": lb.shape_name,
                "ip_addresses": [ip.ip_address for ip in (lb.ip_addresses or [])],
            }

        return {
            "error": f"Unsupported resource type '{resource_type}'. "
                     f"Supported types: instance, loadbalancer."
        }

    except oci.exceptions.ServiceError as exc:
        logger.exception("resolve_ocid failed (OCI ServiceError)")
        return {"error": f"OCI error {exc.status}: {exc.message}"}
    except Exception as exc:
        logger.exception("resolve_ocid failed")
        return {"error": str(exc)}


@mcp.tool()
def resolve_fqdn(fqdn: str) -> dict:
    """
    Resolve a Fully Qualified Domain Name (FQDN) to its IP address.

    Args:
        fqdn: The FQDN to resolve, e.g. 'google.com'.

    Returns:
        A dict with 'fqdn' and 'ip_address' keys, or an 'error' key on failure.
    """
    try:
        ip_address = socket.gethostbyname(fqdn)
        return {"fqdn": fqdn, "ip_address": ip_address}
    except socket.gaierror as exc:
        return {"error": f"Failed to resolve '{fqdn}': {exc}"}
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    """Console-script entry point used by uvx / pipx."""
    mcp.run()


if __name__ == "__main__":
    main()