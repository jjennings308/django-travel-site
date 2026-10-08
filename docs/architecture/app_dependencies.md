# App dependencies

**An arrow `A --> B` means "A imports B".** Imports may only point down the layers (or along
the allowed same-layer arrows). The rules are the "Dependency layers" table in `CLAUDE.md`.
`scripts/check_layers.py` enforces them, and `apps.core.tests.test_layers` runs it as part of
`manage.py test`.

The diagram shows the imports that actually exist (generated from the checker's import scan,
migrations excluded). Every app also imports `core`; those arrows are left out to keep the
diagram readable.

```mermaid
graph TD

    subgraph L5["5 · Site"]
        pages
        admin_tools
    end

    subgraph L4["4 · User content"]
        bucketlists
        trips
        reviews
        recommendations
    end

    subgraph L3["3 · Catalog"]
        locations
        activities
        vendors
        events
    end

    subgraph L2["2 · Platform services"]
        notifications
        media_app
        approval_system
        rewards
    end

    subgraph L1["1 · Identity"]
        accounts
    end

    subgraph L0["0 · Base"]
        core
    end

    pages --> accounts
    pages --> bucketlists
    pages --> trips

    bucketlists --> activities
    bucketlists --> events
    bucketlists --> locations
    bucketlists --> trips

    trips --> activities
    trips --> events
    trips --> locations
    trips --> vendors

    reviews --> activities
    reviews --> events
    reviews --> locations
    reviews --> vendors
    reviews --> trips

    recommendations --> activities
    recommendations --> events
    recommendations --> locations
    recommendations --> trips

    locations --> approval_system
    locations --> media_app
    activities --> approval_system
    activities --> locations
    vendors --> locations
    events --> locations
    events --> activities

    approval_system --> notifications

    accounts --> core
```

Foreign keys to the user model go through `settings.AUTH_USER_MODEL`, so they create a
migration dependency on `accounts` but no import. That is why most apps show no arrow to
`accounts`. For which side of each relationship owns the foreign key, see `fk_direction.md`.
