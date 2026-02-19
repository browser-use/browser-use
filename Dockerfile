# Dockerfile

# Use the official Node.js image.
FROM node:14

# Set the working directory.
WORKDIR /usr/src/app

# Copy package.json and package-lock.json.
COPY package*.json ./

# Install dependencies.
RUN npm install

# Copy the rest of the application code.
COPY . .

# Expose the application port (usually 3000 for Node.js apps).
EXPOSE 3000

# Command to start the application.
CMD [ "npm", "start" ]