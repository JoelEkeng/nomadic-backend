# Driver matching

Matching is designed to avoid PostgreSQL queries in the assignment hot path.

## Redis data

- `driver_locations:geo`: current driver positions, maintained by the location module.
- `driver_locations:data:{driver_id}`: latest location metadata, maintained by the location module.
- `driver_matching:profile:{driver_id}`: cached vehicle type, rating, acceptance rate, and cancellation rate.
- `driver_matching:reservation:{driver_id}`: short-lived assignment lock for a ride request.

Driver profile cache entries should be refreshed when a driver goes online, vehicle approval
changes, or driver quality metrics are recalculated. The match request itself reads only Redis.

## Matching flow

1. Query Redis GEO for nearby drivers around pickup.
2. Load cached matching profiles and skip reserved drivers.
3. Filter by requested vehicle type.
4. Estimate pickup ETA from distance.
5. Rank by distance, ETA, rating, acceptance rate, and cancellation rate.
6. Reserve the best available driver with `SET NX EX`.

The reservation TTL is intentionally short. If the driver does not accept, the lock expires and
the driver can be considered for another request.
