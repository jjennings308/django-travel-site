graph LR

    accounts["accounts.User"]

    locations["locations<br/>(Country, Region, City, POI)"]

    vendors["vendors.Vendor"]

    trips["trips.Trip"]

    bucketlists["bucketlists.BucketItem"]

    reviews["reviews.Review"]

    media["media.Media"]

    notifications["notifications.Notification"]

    recommendations["recommendations.Engine"]

    %% FK ownership
    bucketlists --> accounts
    bucketlists --> locations

    trips --> accounts
    trips --> locations
    trips --> vendors

    reviews --> accounts
    reviews --> vendors
    reviews --> trips

    media --> trips
    media --> bucketlists
    media --> vendors

    notifications --> accounts
    notifications --> trips
    notifications --> reviews

    recommendations --> accounts
    recommendations --> trips
    recommendations --> bucketlists
