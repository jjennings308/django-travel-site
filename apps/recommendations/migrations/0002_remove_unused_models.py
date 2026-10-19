# Site roadmap R19: the five recommendation models were never used (all empty); recommendations are
# computed by services.for_user. Hand-written as plain DeleteModels, children first: the generated
# version removed fields before the unique_together that named them and could not run.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('recommendations', '0001_initial'),
    ]

    operations = [
        migrations.DeleteModel(name='RecommendationFeedback'),
        migrations.DeleteModel(name='RecommendationPerformance'),
        migrations.DeleteModel(name='Recommendation'),
        migrations.DeleteModel(name='UserInterest'),
        migrations.DeleteModel(name='RecommendationRule'),
    ]
