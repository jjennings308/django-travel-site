"""URLs for the trips app.

Mounted at ``/trips/`` (config/urls.py). The two read views set the convention:
the list is the app root and a trip hangs off ``<pk>/``. The editing URLs
follow that, so a trip's edit page is a child of the trip rather than a
sibling of it.
"""

from django.urls import path

from . import calendar_views, checklists, files, history_views, people_views, views

app_name = "trips"

urlpatterns = [
    path("", views.trip_list, name="trip_list"),
    # The signed-in person's own profile. No pk: see the view.
    path("profile/", views.traveler_profile, name="traveler_profile"),
    # "new" cannot collide with "<int:pk>", so it needs no ordering care.
    path("new/", views.trip_create, name="trip_create"),
    path("<int:pk>/", views.trip_detail, name="trip_detail"),
    path("<int:pk>/edit/", views.trip_edit, name="trip_edit"),
    path("<int:pk>/delete/", views.trip_delete, name="trip_delete"),
    path("<int:pk>/share/", views.trip_share, name="trip_share"),
    path("<int:pk>/notify/", views.trip_notify, name="trip_notify"),
    path("<int:pk>/history/", history_views.trip_history, name="trip_history"),
    path("<int:pk>/checklists/new/", checklists.checklist_edit, name="checklist_new"),
    path("<int:pk>/checklists/template/", checklists.checklist_from_template, name="checklist_from_template"),
    path("<int:pk>/checklists/<int:checklist_pk>/", checklists.checklist_edit, name="checklist_edit"),
    path("<int:pk>/checklists/<int:checklist_pk>/delete/", checklists.checklist_delete, name="checklist_delete"),
    path("<int:pk>/checklists/items/<int:item_pk>/tick/", checklists.checklist_tick, name="checklist_tick"),
    path("<int:pk>/history/<int:change_pk>/undo/", history_views.change_undo, name="change_undo"),
    path("<int:pk>/people/", people_views.trip_people, name="trip_people"),
    path("invite/<str:token>/", people_views.invite_accept, name="invite_accept"),
    path("<int:pk>/calendar/", calendar_views.trip_calendar, name="trip_calendar"),
    path("<int:pk>/calendar/reset/", calendar_views.trip_calendar_reset, name="trip_calendar_reset"),
    path("calendar/<str:token>.ics", calendar_views.trip_calendar_feed, name="trip_calendar_feed"),
    path("<int:pk>/budget/", views.trip_budget, name="trip_budget"),
    path("<int:pk>/budget/rates/", views.trip_rates, name="trip_rates"),
    path("<int:pk>/photos/", views.trip_photos, name="trip_photos"),
    path("<int:pk>/map/", views.trip_map, name="trip_map"),
    path("<int:pk>/legs/<int:leg_pk>/", views.leg_edit, name="leg_edit"),
    path("<int:pk>/legs/<int:leg_pk>/delete/", views.leg_delete, name="leg_delete"),
    path("<int:pk>/confirmations/new/", views.confirmation_edit, name="confirmation_new"),
    path("<int:pk>/confirmations/<int:confirmation_pk>/", views.confirmation_edit, name="confirmation_edit"),
    path("<int:pk>/confirmations/<int:confirmation_pk>/delete/", views.confirmation_delete, name="confirmation_delete"),
    path("<int:pk>/confirmations/<int:confirmation_pk>/files/", files.confirmation_file_add, name="confirmation_file_add"),
    path("<int:pk>/files/<int:file_pk>/", files.confirmation_file, name="confirmation_file"),
    path("<int:pk>/files/<int:file_pk>/delete/", files.confirmation_file_delete, name="confirmation_file_delete"),
    path("<int:pk>/days/<int:day_pk>/legs/add/", views.leg_quick_add, name="leg_quick_add"),
    path("<int:pk>/days/<int:day_pk>/travel/", views.day_add_travel, name="day_add_travel"),
    path("<int:pk>/map/data.json", views.trip_map_data, name="trip_map_data"),
    path("<int:pk>/photos/<int:media_pk>/delete/", views.trip_photo_delete, name="trip_photo_delete"),
    path("<int:pk>/photos/<int:media_pk>/cover/", views.trip_photo_cover, name="trip_photo_cover"),
    path("<int:pk>/budget/<int:expense_pk>/", views.expense_edit, name="expense_edit"),
    path("<int:pk>/unshare/", views.trip_unshare, name="trip_unshare"),
    path("<int:pk>/restore/", views.trip_restore, name="trip_restore"),
    # A day is reached through its trip, so the trip's permission check runs
    # first and an unreachable trip is a 404 whatever the day.
    path("<int:trip_pk>/days/new/", views.day_create, name="day_create"),
    path("<int:trip_pk>/days/<int:pk>/", views.day_edit, name="day_edit"),
    path("<int:trip_pk>/days/<int:day_pk>/catalogue/<str:kind>/<int:item_pk>/", views.catalogue_link,
         name="catalogue_link"),
    path(
        "<int:trip_pk>/days/<int:pk>/delete/",
        views.day_delete,
        name="day_delete",
    ),
    # The section type is in the URL so "add a callout" is one link; it is still
    # validated against Section.Type inside the view.
    path(
        "<int:trip_pk>/days/<int:day_pk>/sections/new/<str:section_type>/",
        views.section_create,
        name="section_create",
    ),
    path(
        "<int:trip_pk>/days/<int:day_pk>/sections/<int:pk>/",
        views.section_edit,
        name="section_edit",
    ),
    path("<int:pk>/travel-tables/", views.trip_travel_review, name="trip_travel_review"),
    path("<int:pk>/booklet.pdf", views.trip_pdf, name="trip_pdf"),
    path("<int:pk>/tasks/done/", views.task_offer, name="task_offer"),
    path("<int:pk>/tidy/", views.trip_tidy, name="trip_tidy"),
    path("<int:pk>/tasks/<int:task_pk>/options/", views.task_options, name="task_options"),
    path("<int:pk>/todo/", views.trip_todo, name="trip_todo"),
    path("<int:pk>/tasks/new/", views.task_edit, name="task_new"),
    path("<int:pk>/tasks/<int:task_pk>/", views.task_edit, name="task_edit"),
    path("<int:pk>/tasks/<int:task_pk>/delete/", views.task_delete, name="task_delete"),
    path("<int:pk>/tasks/<int:task_pk>/done/", views.task_done, name="task_done"),
    path("<int:pk>/options/<int:option_pk>/add/", views.option_add, name="option_add"),
    path("<int:pk>/links/<str:kind>/<int:item_pk>/", views.item_links, name="item_links"),
    path("<int:pk>/contacts/new/", views.contact_edit, name="contact_new"),
    path("<int:pk>/contacts/<int:contact_pk>/", views.contact_edit, name="contact_edit"),
    path("<int:pk>/contacts/<int:contact_pk>/delete/", views.contact_delete, name="contact_delete"),
    path("<int:pk>/info/new/", views.info_edit, name="info_new"),
    path("<int:pk>/info/<int:info_pk>/", views.info_edit, name="info_edit"),
    path("<int:pk>/info/<int:info_pk>/delete/", views.info_delete, name="info_delete"),
    path("<int:pk>/days/<int:day_pk>/activities/new/", views.activity_edit, name="activity_new"),
    path("<int:pk>/days/<int:day_pk>/activities/<int:activity_pk>/", views.activity_edit, name="activity_edit"),
    path("<int:pk>/days/<int:day_pk>/activities/<int:activity_pk>/delete/", views.activity_delete,
         name="activity_delete"),
    path("<int:pk>/days/<int:day_pk>/stays/new/", views.stay_new, name="stay_new"),
    path("<int:pk>/stays/<int:stay_pk>/", views.stay_edit, name="stay_edit"),
    path("<int:pk>/stays/<int:stay_pk>/delete/", views.stay_delete, name="stay_delete"),
    path("<int:pk>/notes/<int:note_pk>/hide/", views.trip_note_hide, name="trip_note_hide"),
    path("<int:pk>/confirmations/<str:kind>/<int:item_pk>/", views.item_confirmations, name="item_confirmations"),
    path("<int:pk>/tasks/<int:task_pk>/link/", views.task_link, name="task_link"),
    path(
        "<int:trip_pk>/days/<int:day_pk>/sections/<int:pk>/legs/",
        views.section_to_legs,
        name="section_to_legs",
    ),
    path(
        "<int:trip_pk>/days/<int:day_pk>/sections/<int:pk>/travel-notes/",
        views.section_to_travel_notes,
        name="section_to_travel_notes",
    ),
    path(
        "<int:trip_pk>/days/<int:day_pk>/sections/<int:pk>/delete/",
        views.section_delete,
        name="section_delete",
    ),
    # Comments hang off whatever they are about, so the URL names the kind of
    # target and its pk rather than a trip. "task" is the booking task; the view
    # maps every name to one model and 404s on an unknown one, so a hand-written
    # URL cannot name an arbitrary content type.
    path(
        "comments/<str:kind>/<int:pk>/",
        views.comment_create,
        name="comment_create",
    ),
    # A comment is edited and deleted by its own id, not by its target: editing
    # is a property of the comment ("is it mine?"), not of the page it sits on.
    path("comments/<int:pk>/edit/", views.comment_edit, name="comment_edit"),
]
