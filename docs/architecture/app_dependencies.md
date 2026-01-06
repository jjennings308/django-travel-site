graph TD

    core["core<br/>(settings, utils, base models)"]

    accounts["accounts<br/>(custom user, profiles)"]

    locations["locations<br/>(countries, regions, cities, POIs)"]

    vendors["vendors<br/>(tour operators, hotels, restaurants)"]

    trips["trips<br/>(itineraries, travel days, bookings)"]

    events["events<br/>(date, time, place)"]

    bucketlists["bucketlists<br/>(user bucket list items)"]

    reviews["reviews<br/>(ratings, comments)"]

    media["media<br/>(photos, videos, uploads)"]

    notifications["notifications<br/>(email, alerts)"]

    recommendations["recommendations<br/>(AI & rules engine)"]

    admin_tools["admin_tools<br/>(reports, moderation)"]

    activities["activities<br/>(skill level, goal, resources, style, time needed)"]

    core --> accounts
    core --> locations
    core --> activities

    accounts --> bucketlists
    accounts --> trips
    accounts --> admin_tools
    accounts --> recommendations

    locations --> vendors
    locations --> trips
    locations --> bucketlists
    locations --> media

    activities --> bucketlists
    activities --> media  
     
    vendors --> trips
    vendors --> media

    trips --> events
    trips --> locations
    trips --> activities
    trips --> vendors
    trips --> recommendations
    trips --> notifications
    trips --> media

    bucketlists --> media
    bucketlists --> recommendations
    bucketlists --> notifications

    events --> locations
    events --> activities
    events --> bucketlists
    events --> media   
    events --> notifications 

    reviews --> admin_tools
    reviews --> notifications
    reviews --> vendors
    reviews --> accounts
    reviews --> vendors    
    reviews --> activities 
    reviews --> events     
    reviews --> locations  
    reviews --> trips      