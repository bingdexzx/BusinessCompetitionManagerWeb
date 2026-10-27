from django.urls import path

from apps.competition.companies import views

urlpatterns = [
    path('competitions/<int:cid>/companies', views.CompanyListView.as_view()),
    path('competitions/<int:cid>/companies/<int:pk>/tables/<str:table>',
         views.CompanyTableView.as_view()),
    path('competitions/<int:cid>/companies/<int:pk>/fields', views.CompanyFieldUpdateView.as_view()),
    path('competitions/<int:cid>/companies/<int:pk>/industry-fields',
         views.CompanyIndustryFieldsView.as_view()),
    path('competitions/<int:cid>/companies/<int:pk>/region', views.CompanyRegionView.as_view()),
]
