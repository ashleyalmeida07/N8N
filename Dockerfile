FROM n8nio/n8n:latest

USER root

# Set environment variables
ENV N8N_HOST=0.0.0.0
ENV N8N_PORT=5678
ENV N8N_PROTOCOL=https
ENV GENERIC_TIMEZONE=Asia/Kolkata
ENV N8N_SECURE_COOKIE=false
ENV N8N_USER_FOLDER=/data

# Expose port
EXPOSE 5678
