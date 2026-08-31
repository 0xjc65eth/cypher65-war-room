# SHA-256 pool endpoint security

User-controlled pool endpoints are an SSRF and network-scanning surface.

The foundation currently enforces:

- only `stratum+tcp`, `stratum+ssl` and `stratum+tls` syntax;
- explicit valid port, no userinfo/path/query/fragment/control characters;
- ambiguous numeric and Unicode hostnames fail closed;
- approved default Stratum ports, with explicit custom-port policy;
- all resolved DNS answers must pass policy;
- loopback, link-local, unspecified, multicast, reserved and non-public
  destinations are blocked;
- IPv4-mapped IPv6 is normalized before validation;
- private pools require both local-pool mode and administrator authorization.

The parser and policy perform no socket operations. A future connector must pin
the connection to an address returned by the policy and must not resolve the
hostname again implicitly, preventing DNS rebinding between validation and
connect. It must add per-user/tenant/global limits, timeouts, message-size caps,
circuit breaking and audit logs before active discovery is enabled.

Existing Braiins purchase and ASIC pool-change paths are not universal discovery
and must be migrated to this policy in a separate compatibility-tested lot before
accepting arbitrary endpoints.
