from django.contrib import admin

from apps.competition.settlement.models import (
    AwardDefinition, AwardGrant, AwardResult, ScoringCriterion, SettlementRun,
)

admin.site.register(ScoringCriterion)
admin.site.register(AwardDefinition)
admin.site.register(AwardGrant)
admin.site.register(SettlementRun)
admin.site.register(AwardResult)
