# media_app/forms.py
from django import forms

from apps.core.utils.images import shrink_image

from .models import Media

MAX_PICTURE_MB = 20
MAX_PICTURE_SIDE = 2400


class PictureFormMixin:
    """Optional picture for a ModelForm whose model has ``featured_media`` (FK to
    Media). Call ``setup_picture()`` in ``__init__`` and ``save_picture(user)``
    after the instance is saved. Declared fields on a plain mixin are not
    collected by the form metaclass, so the fields are added in setup."""

    def setup_picture(self):
        self.fields["picture"] = forms.ImageField(
            required=False, label="Picture",
            help_text=f"Optional. JPEG, PNG, WebP or iPhone HEIC, up to {MAX_PICTURE_MB} MB.",
            widget=forms.ClearableFileInput(attrs={"class": "sbl-input", "accept": "image/*,.heic,.heif"}),
        )
        self.fields["remove_picture"] = forms.BooleanField(required=False, label="Remove the current picture")

    def clean_picture(self):
        picture = self.cleaned_data.get("picture")
        if picture and picture.size > MAX_PICTURE_MB * 1024 * 1024:
            raise forms.ValidationError(f"That picture is over {MAX_PICTURE_MB} MB.")
        return picture

    def save_picture(self, user):
        """Store a new upload as Media and link it, or unlink on "remove"."""
        instance = self.instance
        picture = self.cleaned_data.get("picture")
        if picture:
            media = Media(
                file=shrink_image(picture, MAX_PICTURE_SIDE) or picture, uploaded_by=user, media_type="image",
                title=str(instance)[:200], alt_text=str(instance)[:200], content_object=instance,
            )
            media.save()
            instance.featured_media = media
            instance.save(update_fields=["featured_media"])
        elif self.cleaned_data.get("remove_picture") and instance.featured_media_id:
            instance.featured_media = None
            instance.save(update_fields=["featured_media"])
