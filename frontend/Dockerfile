FROM node:20-alpine

WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm install

# Copy application
COPY . .

ARG NEXT_PUBLIC_API_URL=http://192.168.110.26:8000
ENV NEXT_PUBLIC_API_URL=\n
# Build
RUN npm run build

# Expose port
EXPOSE 3000

# Run
CMD ["npm", "start"]
