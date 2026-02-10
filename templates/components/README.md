# ShareBucketList Component Library

Complete Tailwind CSS component system for your travel application.

## 📂 What's Included

```
components/
├── cards/
│   ├── stat_card.html          # Metric/KPI display cards
│   ├── action_card.html        # Interactive CTA cards
│   └── progress_card.html      # Progress tracking cards
├── feedback/
│   ├── empty_state.html        # No-data placeholders
│   └── loading_spinner.html    # Loading indicators
├── sections/
│   └── hero.html               # Landing page hero sections
├── home_example.html           # Homepage using components
└── README.md                   # This file
```

## 🚀 Quick Start

### 1. Copy Components to Your Project

```bash
# From your project root
cp -r components/* templates/components/
```

### 2. Follow the Setup Guide

Open `TAILWIND_SETUP_GUIDE.md` and follow Steps 1-7 in order.

**Critical first steps:**
1. Configure `tailwind.config.js` with your brand colors
2. Update `templates/base.html` to load Tailwind
3. Start Tailwind dev server: `python manage.py tailwind start`

## 🎨 Design System

### Color Palette

**Earth Tones (Primary Brand)**
- `earth-clay` - #7A4E2D (primary)
- `earth-olive` - #556B2F (secondary)
- `earth-ochre` - #C58B2A (accent/CTA)
- `earth-sage` - #8CA66B (soft green)

**Warm Neutrals**
- `warm-50` through `warm-900` (light to dark)

### Using Colors in Components

All components accept a `color` parameter:

```django
{# Clay (primary brand) #}
{% include 'components/cards/stat_card.html' with color="clay" ... %}

{# Olive (secondary) #}
{% include 'components/cards/stat_card.html' with color="olive" ... %}

{# Ochre (accent/CTA) #}
{% include 'components/cards/stat_card.html' with color="ochre" ... %}

{# Sage (soft green) #}
{% include 'components/cards/stat_card.html' with color="sage" ... %}
```

## 📦 Component Reference

### Cards

#### Stat Card
Display metrics and KPIs.

```django
{% include 'components/cards/stat_card.html' with 
   value=42 
   label="Countries Visited" 
   icon="bi-globe" 
   color="clay" %}
```

**Parameters:**
- `value` (required) - Number or text
- `label` (required) - Descriptive label
- `icon` (optional) - Bootstrap icon class
- `color` (optional) - clay|olive|ochre|sage
- `animate` (optional) - Hover animation (default: true)

---

#### Action Card
Interactive cards with call-to-action.

```django
{% include 'components/cards/action_card.html' with 
   title="Plan Trip" 
   icon="bi-map" 
   url="trips:plan" 
   description="Start planning" 
   button_text="Get Started" 
   color="olive" %}
```

**Parameters:**
- `title` (required) - Card heading
- `url` (required) - Django URL name
- `icon` (optional) - Bootstrap icon
- `description` (optional) - Supporting text
- `button_text` (optional) - CTA text
- `color` (optional) - Color variant
- `external` (optional) - Use raw URL (default: false)

---

#### Progress Card
Show completion progress.

```django
{% include 'components/cards/progress_card.html' with 
   label="Bucket List" 
   percentage=65 
   sublabel="26 of 40 completed" %}
```

**Parameters:**
- `label` (required) - What's being tracked
- `percentage` (required) - 0-100 value
- `sublabel` (optional) - Additional context
- `color` (optional) - Color variant
- `show_count` (optional) - Show "X/Y" format
- `completed` (optional) - Number completed
- `total` (optional) - Total number

---

### Feedback

#### Empty State
Friendly no-data message.

```django
{% include 'components/feedback/empty_state.html' with 
   title="No trips yet" 
   message="Start planning" 
   icon="bi-airplane" 
   cta_url="trips:plan" 
   cta_text="Plan a Trip" %}
```

**Parameters:**
- `title` (required) - Main heading
- `message` (optional) - Explanatory text
- `icon` (optional) - Bootstrap icon
- `cta_url` (optional) - Button URL
- `cta_text` (optional) - Button text
- `color` (optional) - Button color

---

#### Loading Spinner
Show loading state.

```django
{# Inline #}
{% include 'components/feedback/loading_spinner.html' with size="md" text="Loading..." %}

{# Full-page overlay #}
{% include 'components/feedback/loading_spinner.html' with overlay=True text="Processing..." %}
```

**Parameters:**
- `size` (optional) - sm|md|lg
- `text` (optional) - Loading message
- `overlay` (optional) - Full-page overlay
- `color` (optional) - Spinner color

---

### Sections

#### Hero Section
Large header for landing pages.

```django
{% include 'components/sections/hero.html' with 
   title="ShareBucketList" 
   subtitle="Plan it. Live it. Share it." 
   cta_primary_text="Get Started" 
   cta_primary_url="register" 
   cta_secondary_text="Learn More" 
   cta_secondary_url="core:about" %}
```

**Parameters:**
- `title` (required) - Main headline
- `subtitle` (optional) - Supporting text
- `cta_primary_text` (optional) - Primary button text
- `cta_primary_url` (optional) - Primary button URL
- `cta_secondary_text` (optional) - Secondary button text
- `cta_secondary_url` (optional) - Secondary button URL
- `image_url` (optional) - Hero image
- `gradient` (optional) - Custom gradient

---

## 💡 Usage Examples

### Dashboard with Stats Grid

```django
<div class="grid grid-cols-2 lg:grid-cols-4 gap-6">
  {% include 'components/cards/stat_card.html' with 
     value=stats.trips label="Trips" icon="bi-airplane" color="clay" %}
  
  {% include 'components/cards/stat_card.html' with 
     value=stats.countries label="Countries" icon="bi-globe" color="olive" %}
  
  {% include 'components/cards/stat_card.html' with 
     value=stats.activities label="Activities" icon="bi-star" color="ochre" %}
  
  {% include 'components/cards/stat_card.html' with 
     value=stats.points label="Points" icon="bi-trophy" color="sage" %}
</div>
```

### Feature Cards Grid

```django
<div class="grid md:grid-cols-3 gap-8">
  {% include 'components/cards/action_card.html' with 
     title="Bucket Lists" 
     icon="bi-list-check" 
     url="bucketlists:dashboard" 
     description="Create wish lists" 
     color="clay" %}
  
  {% include 'components/cards/action_card.html' with 
     title="Trip Planning" 
     icon="bi-map" 
     url="trips:dashboard" 
     description="Plan your adventures" 
     color="olive" %}
  
  {% include 'components/cards/action_card.html' with 
     title="Rewards" 
     icon="bi-trophy" 
     url="rewards:dashboard" 
     description="Track achievements" 
     color="ochre" %}
</div>
```

### Empty State with CTA

```django
{% if not trips %}
  {% include 'components/feedback/empty_state.html' with 
     title="No trips yet" 
     message="Start planning your first adventure today" 
     icon="bi-airplane" 
     cta_url="trips:plan" 
     cta_text="Plan Your First Trip" 
     color="olive" %}
{% endif %}
```

---

## 🎯 Best Practices

### Color Consistency
Use color variants consistently:
- **Clay** → Primary brand elements, main CTAs
- **Olive** → Nature/travel features, secondary actions
- **Ochre** → Rewards, achievements, urgent CTAs
- **Sage** → Success states, completion indicators

### Grid Layouts
Components work in Tailwind's grid:

```django
{# 2-column mobile, 4-column desktop #}
<div class="grid grid-cols-2 lg:grid-cols-4 gap-6">
  {# stat cards here #}
</div>

{# 1-column mobile, 3-column desktop #}
<div class="grid md:grid-cols-3 gap-8">
  {# action cards here #}
</div>
```

### Responsive Design
All components are mobile-first and responsive by default.

---

## 🔄 Migration from Bootstrap

### Before (Bootstrap)
```django
<div class="col-md-3">
  <div class="card">
    <div class="card-body text-center">
      <div class="display-4 text-primary">{{ value }}</div>
      <small class="text-muted">{{ label }}</small>
    </div>
  </div>
</div>
```

### After (Tailwind Component)
```django
{% include 'components/cards/stat_card.html' with 
   value=value label=label icon="bi-star" color="clay" %}
```

**Benefits:**
- 70% less code
- Consistent styling
- Easy global updates
- Built-in accessibility
- Responsive by default

---

## 📚 Documentation

Each component has extensive inline documentation. Open any `.html` file to see:
- Complete parameter descriptions
- Usage examples
- Default values
- Common patterns

---

## 🆘 Getting Help

1. **Setup issues?** → See `TAILWIND_SETUP_GUIDE.md`
2. **Component usage?** → Check inline docs in component files
3. **Styling issues?** → Verify Tailwind config has your brand colors

---

## ✅ Next Steps

1. Follow `TAILWIND_SETUP_GUIDE.md` Steps 1-7
2. Start with homepage (use `home_example.html` as template)
3. Convert navigation and dashboard pages
4. Migrate remaining pages one at a time

---

**Ready to build beautiful, consistent UIs with your earth-tone branding!**
