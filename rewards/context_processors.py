def rewards_context(request):
    """Add rewards-related context to all templates"""
    if not request.user.is_authenticated:
        return {}
    
    from rewards.models import UserRewardsMembership
    
    memberships = request.user.rewards_memberships.all()
    expiring_count = sum(1 for m in memberships if m.is_tier_expiring_soon)
    
    return {
        'rewards_expiring_count': expiring_count,
    }