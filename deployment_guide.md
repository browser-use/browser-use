# Deployment Guide

This guide provides step-by-step instructions for deploying the `browser-use` application to AWS and Heroku.

---

## Deploying to AWS Elastic Beanstalk

1. **Install the AWS CLI:**
   - Download and install the [AWS CLI](https://aws.amazon.com/cli/):
     ```bash
     pip install awscli
     ```
   - Configure the CLI with your AWS credentials:
     ```bash
     aws configure
     ```

2. **Install EB CLI:**
   - Install the Elastic Beanstalk CLI:
     ```bash
     pip install awsebcli
     ```

3. **Initialize Elastic Beanstalk:**
   - From your repository folder, initialize Elastic Beanstalk:
     ```bash
     eb init
     ```
   - Follow the prompts to select your region and application name.

4. **Create a Dockerrun.aws.json File:**
   - Add the following file in the repository root to instruct AWS on how to run the Docker image:
     ```json
     {
       "AWSEBDockerrunVersion": "1",
       "Image": {
         "Name": "<YOUR_DOCKER_IMAGE_NAME>",
         "Update": "true"
       },
       "Ports": [
         {
           "ContainerPort": "3000"
         }
       ]
     }
     ```

5. **Deploy the App to AWS Elastic Beanstalk:**
   - Create and deploy an environment:
     ```bash
     eb create <environment-name>
     ```
   - Open the deployed URL provided by Elastic Beanstalk.

---

## Deploying to Heroku

1. **Install the Heroku CLI:**
   - Download and install the [Heroku CLI](https://devcenter.heroku.com/articles/heroku-cli):
     ```bash
     curl https://cli-assets.heroku.com/install.sh | sh
     ```

2. **Login to Heroku:**
   - Log in to the Heroku CLI:
     ```bash
     heroku login
     ```

3. **Create a Heroku App:**
   - Create an app in your repository by running:
     ```bash
     heroku create
     ```
   - Note the app name and the corresponding URL.

4. **Deploy the Dockerized Application:**
   - Add and deploy your Docker image to Heroku:
     ```bash
     heroku container:push web
     heroku container:release web
     ```

5. **Open Your Application:**
   - Launch your Heroku app in a browser:
     ```bash
     heroku open
     ```

---

Let me know if you need further guidance!