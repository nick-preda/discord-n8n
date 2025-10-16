## How to start
### Build the docker bot:
docker build -t discord-events-bot . 

### Run the docker bot:
docker run --rm --env-file .env discord-events-bot