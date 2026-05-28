from django.urls import path

from .views import CubeCreateView, CubeDetailView, CubeListView, HowThisWorksView, card_autocomplete, submit_card

urlpatterns = [
    path("", CubeListView.as_view(), name="cube-list"),
    path("about/", HowThisWorksView.as_view(), name="how-this-works"),
    path("cubes/new/", CubeCreateView.as_view(), name="cube-create"),
    path("cubes/<int:pk>/", CubeDetailView.as_view(), name="cube-detail"),
    path("cubes/<int:pk>/submit/", submit_card, name="cube-submit"),
    path("cubes/<int:pk>/card-autocomplete/", card_autocomplete, name="cube-card-autocomplete"),
]
