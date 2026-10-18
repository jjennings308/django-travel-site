# ============================================
# rewards/views.py
# ============================================
"""The rewards-program catalogue (browse and detail).

Memberships themselves live on the travel profile (``trips.RewardsMembership``, keyed to the
traveller; site roadmap R11). The old membership pages redirect there, by URL name, so this app
never imports trips.
"""
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import RewardsProgramSearchForm
from .models import RewardsProgram, RewardsProgramType


@login_required
def to_travel_profile(request, **kwargs):
    """The old membership pages: memberships are on the travel profile now."""
    url = reverse("trips:traveler_profile")
    program = request.GET.get("program", "")
    return redirect(f"{url}?program={program}#memberships" if program.isdigit() else f"{url}#memberships")


def programs_browse(request):
    """Browse available rewards programs (public page)"""
    programs = RewardsProgram.objects.filter(is_active=True)
    form = RewardsProgramSearchForm(request.GET)
    if form.is_valid():
        search = form.cleaned_data.get("search")
        if search:
            programs = programs.filter(
                Q(name__icontains=search) | Q(company__icontains=search) | Q(description__icontains=search)
            )
        program_type = form.cleaned_data.get("program_type")
        if program_type:
            programs = programs.filter(program_type=program_type)

    programs_by_type = {}
    for prog_type in RewardsProgramType:
        type_programs = [p for p in programs if p.program_type == prog_type.value]
        if type_programs:
            programs_by_type[prog_type.label] = type_programs

    return render(request, "rewards/programs_browse.html",
                  {"programs": programs, "programs_by_type": programs_by_type, "form": form})


def program_detail(request, program_id):
    """View details about a specific rewards program"""
    program = get_object_or_404(RewardsProgram, id=program_id, is_active=True)
    return render(request, "rewards/program_detail.html", {"program": program})
