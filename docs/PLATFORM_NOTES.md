# Platform notes

## Facebook
Configure a Meta developer app, Page access token and the permissions required for the Page publishing features you use. The project keeps publishing inside the official Graph API; it does not automate the Facebook website.

## YouTube
The uploader uses OAuth and `videos.insert`. For scheduled publication, YouTube requires the uploaded video's privacy status to be `private` and accepts an ISO 8601 `publishAt` value.

## TikTok
The project uses Content Posting API Direct Post. It queries creator info before initializing the post, uses the creator's allowed privacy options, uploads local video in chunks, stores `publish_id`, and polls the official status endpoint. TikTok's current documentation states that unaudited Direct Post clients are restricted to private viewing until the required audit/approval is completed.
