graph TD

    core["core<br/>(settings, utils, base models)"]

    accounts["accounts<br/>(custom user, profiles)"]

    locations["locations<br/>(countries, regions, cities, POIs)"]

    vendors["vendors<br/>(tour operators, hotels, restaurants)"]

    trips["trips<br/>(itineraries, travel days, bookings)"]

    bucketlists["bucketlists<br/>(user bucket list items)"]

    reviews["reviews<br/>(ratings, comments)"]

    media["media<br/>(photos, videos, uploads)"]

    notifications["notifications<br/>(email, alerts)"]

    recommendations["recommendations<br/>(AI & rules engine)"]

    admin_tools["admin_tools<br/>(reports, moderation)"]

    core --> accounts

    core --> locations

    accounts --> bucketlists
    accounts --> trips
    accounts --> reviews

    locations --> vendors
    locations --> trips
    locations --> bucketlists

    vendors --> trips
    vendors --> reviews

    trips --> media
    bucketlists --> media

    trips --> notifications
    reviews --> notifications

    bucketlists --> recommendations
    trips --> recommendations

    accounts --> admin_tools
    reviews --> admin_tools
