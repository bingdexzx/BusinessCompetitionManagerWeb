from django.contrib import admin

from apps.competition.settlement.models import AwardRule, AwardResult, ScoringCriterion, SettlementRun

admin.site.register(ScoringCriterion)
admin.site.register(AwardRule)
admin.site.register(SettlementRun)
admin.site.register(AwardResult)
