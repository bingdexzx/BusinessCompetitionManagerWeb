from django.urls import path

from apps.competition.contracts import views

urlpatterns = [
    path('competitions/<int:cid>/contracts', views.ContractListCreateView.as_view()),
    path('competitions/<int:cid>/contracts/<int:pk>', views.ContractDetailView.as_view()),
    path('competitions/<int:cid>/contracts/<int:pk>/submit', views.ContractSubmitView.as_view()),
    path('competitions/<int:cid>/contracts/<int:pk>/confirm', views.ContractConfirmView.as_view()),
    path('competitions/<int:cid>/contracts/<int:pk>/effects', views.ContractEffectsView.as_view()),
    path('competitions/<int:cid>/contracts/<int:pk>/ledger', views.ContractLedgerView.as_view()),
    path('competitions/<int:cid>/contracts/<int:pk>/request-modify',
         views.ContractRequestModifyView.as_view()),
    path('competitions/<int:cid>/contracts/<int:pk>/modify/review',
         views.ContractModifyReviewView.as_view()),
    path('competitions/<int:cid>/contracts/<int:pk>/modify/other-party',
         views.ContractModifyOtherPartyView.as_view()),
    path('competitions/<int:cid>/contracts/<int:pk>/modify/submit',
         views.ContractModifySubmitView.as_view()),
    path('competitions/<int:cid>/contracts/<int:pk>/backfill/review',
         views.ContractBackfillReviewView.as_view()),
]
