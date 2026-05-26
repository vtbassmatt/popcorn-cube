from django.conf import settings


def deployment_details(request):
    repo_url = settings.REPO_URL
    if settings.COMMIT_HASH != 'dev' and '://github.com/' in repo_url:
        repo_url += f"/commit/{settings.COMMIT_HASH}"
    return {
        "COMMIT_HASH": settings.COMMIT_HASH,
        "DEPLOY_REF": settings.DEPLOY_REF,
        "REPO_URL": repo_url,
    }


def choose_stars(request):
    return { 'STARS_ARE_GO': request.user and request.user.username == 'ross' }
