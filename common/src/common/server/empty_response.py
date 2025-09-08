from fastapi import Response
def empty():
    return Response(status_code=204)