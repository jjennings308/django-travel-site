# bucketlists/photos.py
"""Photos on a goal at any stage, and personal albums ("My albums").

A goal's photos are Media attached to the BucketListItem (``item.photos()``), added
here or on the "mark done" page. A personal album is a media_app.MediaAlbum with no
trip (trip albums are ``Trip.album``, managed in trips): it gathers the owner's own
photos from goals and trips, or photos uploaded straight into it (Media attached to
the album, deleted with it). Albums are private, or public on the owner's public
bucket list when their profile is public.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.utils.breadcrumbs import build_breadcrumbs
from apps.media_app.models import AlbumMedia, Media, MediaAlbum
from apps.trips.models import Trip

from .forms import AlbumForm, PhotosForm
from .models import BucketListItem


def _plural(n, word="photo"):
    return f"{n} {word}{'s' if n != 1 else ''}"


# ---- a goal's photos ---------------------------------------------------------------------
@login_required
def item_photos(request, pk):
    item = get_object_or_404(BucketListItem, pk=pk, user=request.user)
    form = PhotosForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        files = form.cleaned_data["photos"]
        item.add_photos(files, request.user)
        messages.success(request, f"Added {_plural(len(files))}.")
        return redirect("bucketlists:item_photos", pk=item.pk)
    return render(request, "bucketlists/item_photos.html", {
        "item": item, "photos": item.photos(), "form": form,
        "breadcrumb_list": build_breadcrumbs([("Bucket list", "bucketlists:dashboard"), (item.title, None), ("Photos", None)]),
    })


@login_required
@require_POST
def item_photo_delete(request, pk, media_pk):
    item = get_object_or_404(BucketListItem, pk=pk, user=request.user)
    media = get_object_or_404(item.photos(), pk=media_pk)
    albums = list(MediaAlbum.objects.filter(album_media_items__media=media))
    media.delete()
    for album in albums:
        album.ensure_cover()
    messages.success(request, "Photo removed.")
    return redirect("bucketlists:item_photos", pk=item.pk)


# ---- personal albums ---------------------------------------------------------------------
def _personal():
    return MediaAlbum.objects.filter(trip__isnull=True)


def _own_album(request, pk):
    return get_object_or_404(_personal(), pk=pk, user=request.user)


def _my_photos(user):
    """Photos the user added to their goals or trips, newest first (what an album can borrow)."""
    types = [ContentType.objects.get_for_model(BucketListItem), ContentType.objects.get_for_model(Trip)]
    return (Media.objects.filter(uploaded_by=user, media_type="image", content_type__in=types)
            .order_by("-created_at"))


@login_required
def albums(request):
    mine = (_personal().filter(user=request.user).select_related("cover_image")
            .order_by("-updated_at"))
    return render(request, "bucketlists/albums.html", {
        "albums": mine,
        "breadcrumb_list": build_breadcrumbs([("My adventures", "bucketlists:adventures"), ("Albums", None)]),
    })


@login_required
def album_new(request):
    form = AlbumForm(request.POST or None, initial={"privacy": "private"})
    if request.method == "POST" and form.is_valid():
        album = form.save(commit=False)
        album.user = request.user
        album.save()
        messages.success(request, f"Album “{album.title}” made. Add some photos.")
        return redirect("bucketlists:album_pick", pk=album.pk)
    return render(request, "bucketlists/album_form.html", {
        "form": form, "album": None,
        "breadcrumb_list": build_breadcrumbs([("My adventures", "bucketlists:adventures"), ("Albums", "bucketlists:albums"), ("New", None)]),
    })


@login_required
def album_edit(request, pk):
    album = _own_album(request, pk)
    form = AlbumForm(request.POST or None, instance=album)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Album saved.")
        return redirect("bucketlists:album_detail", pk=album.pk)
    return render(request, "bucketlists/album_form.html", {
        "form": form, "album": album,
        "breadcrumb_list": build_breadcrumbs([("My adventures", "bucketlists:adventures"), ("Albums", "bucketlists:albums"),
                                              (album.title, ("bucketlists:album_detail", {"pk": album.pk})), ("Edit", None)]),
    })


def album_detail(request, pk):
    """The owner sees and manages it; anyone sees a public album of a public profile."""
    album = get_object_or_404(_personal().select_related("user", "cover_image"), pk=pk)
    is_owner = request.user.is_authenticated and request.user.pk == album.user_id
    if not is_owner and not (album.privacy == "public" and album.user.profile_visibility == "public"):
        raise Http404
    form = PhotosForm(request.POST or None, request.FILES or None) if is_owner else None
    if request.method == "POST":
        if not is_owner:
            raise Http404
        if form.is_valid():
            from apps.core.utils.images import shrink_image
            from apps.media_app.forms import MAX_PICTURE_SIDE
            from apps.media_app.quota import check, size_of
            check(request.user, size_of(form.cleaned_data["photos"]))  # the storage limit (R15)
            media = []
            for f in form.cleaned_data["photos"]:
                m = Media(file=shrink_image(f, MAX_PICTURE_SIDE) or f, uploaded_by=request.user, media_type="image",
                          title=album.title[:200], alt_text=album.title[:200], content_object=album,
                          privacy=album.privacy)
                m.save()
                media.append(m)
            album.add(media)
            messages.success(request, f"Added {_plural(len(media))}.")
            return redirect("bucketlists:album_detail", pk=album.pk)
    crumbs = ([("My adventures", "bucketlists:adventures"), ("Albums", "bucketlists:albums"), (album.title, None)] if is_owner
              else [(f"@{album.user.username}", ("bucketlists:public_list", {"username": album.user.username})), (album.title, None)])
    return render(request, "bucketlists/album_detail.html", {
        "album": album, "items": album.items(), "is_owner": is_owner, "form": form,
        "breadcrumb_list": build_breadcrumbs(crumbs),
    })


@login_required
def album_pick(request, pk):
    """Choose photos from your goals and trips to add to the album."""
    album = _own_album(request, pk)
    in_album = set(album.album_media_items.values_list("media_id", flat=True))
    available = [m for m in _my_photos(request.user) if m.pk not in in_album]
    if request.method == "POST":
        wanted = {int(v) for v in request.POST.getlist("media") if v.isdigit()}
        added = album.add([m for m in reversed(available) if m.pk in wanted])
        messages.success(request, f"Added {_plural(len(added))}.")
        return redirect("bucketlists:album_detail", pk=album.pk)
    return render(request, "bucketlists/album_pick.html", {
        "album": album, "available": available,
        "breadcrumb_list": build_breadcrumbs([("My adventures", "bucketlists:adventures"), ("Albums", "bucketlists:albums"),
                                              (album.title, ("bucketlists:album_detail", {"pk": album.pk})), ("Add photos", None)]),
    })


@login_required
@require_POST
def album_remove(request, pk, media_pk):
    """Take a photo out of the album. A photo uploaded into the album is deleted; one
    borrowed from a goal or trip stays there."""
    album = _own_album(request, pk)
    entry = get_object_or_404(AlbumMedia.objects.select_related("media"), album=album, media_id=media_pk)
    media = entry.media
    if media.content_type_id == ContentType.objects.get_for_model(MediaAlbum).pk and media.object_id == album.pk:
        media.delete()
    else:
        entry.delete()
    album.ensure_cover()
    messages.success(request, "Photo taken out of the album.")
    return redirect("bucketlists:album_detail", pk=album.pk)


@login_required
@require_POST
def album_cover(request, pk, media_pk):
    album = _own_album(request, pk)
    entry = get_object_or_404(AlbumMedia, album=album, media_id=media_pk)
    album.cover_image_id = entry.media_id
    album.save(update_fields=["cover_image"])
    messages.success(request, "Cover photo set.")
    return redirect("bucketlists:album_detail", pk=album.pk)


@login_required
@require_POST
def album_delete(request, pk):
    """Delete the album and the photos uploaded into it; borrowed photos stay on their goals and trips."""
    album = _own_album(request, pk)
    Media.objects.filter(content_type=ContentType.objects.get_for_model(MediaAlbum), object_id=album.pk).delete()
    title = album.title
    album.delete()
    messages.success(request, f"Album “{title}” deleted.")
    return redirect("bucketlists:albums")
