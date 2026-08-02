# Real-time driver location

Live driver coordinates are stored in Redis, not PostgreSQL.

## Redis keys

- `driver_locations:geo`: Redis GEO index. Member is `driver_id`; score is Redis' internal geohash.
- `driver_locations:last_seen`: sorted set keyed by `driver_id`; score is the update timestamp epoch.
- `driver_locations:data:{driver_id}`: hash containing the latest latitude, longitude, and timestamp.

Location updates use a non-transactional Redis pipeline:

1. `GEOADD` updates the driver's position.
2. `HSET` writes latest metadata.
3. `EXPIRE` applies a TTL to the metadata hash.
4. `ZADD` records last-seen time for cleanup.

## Expiration policy

Metadata hashes expire automatically after the configured location TTL, currently 90 seconds.
Redis GEO members do not have per-member TTLs, so stale GEO members are removed by scanning
`driver_locations:last_seen` with `ZRANGEBYSCORE` and deleting members older than the cutoff.
Nearby-driver reads also trigger cleanup before querying.

## Persistence strategy

PostgreSQL should store durable driver, trip, and audit records only. Do not persist every GPS
point. Persist location-derived facts only at business boundaries, such as trip pickup/dropoff
coordinates, matched driver id, route summary, or periodic coarse analytics snapshots.
