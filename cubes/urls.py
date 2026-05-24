from django.urls import path
from django.views.generic import TemplateView

from .views import CubeCreateView, CubeDetailView, CubeListView, submit_card

urlpatterns = [
    path("", CubeListView.as_view(), name="cube-list"),
    path(
        "favicon-preview/",
        TemplateView.as_view(template_name="cubes/favicon_preview.html"),
        name="favicon-preview",
    ),
    path("cubes/new/", CubeCreateView.as_view(), name="cube-create"),
    path("cubes/<int:pk>/", CubeDetailView.as_view(), name="cube-detail"),
    path("cubes/<int:pk>/submit/", submit_card, name="cube-submit"),
]
