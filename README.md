# Professional Telegram Muxer Bot

A powerful, containerized Telegram bot designed to professionally mux (combine) video, audio, and subtitle files using FFmpeg. It offers a streamlined workflow, intelligent file handling, and easy deployment with Docker.

![Bot Demo](https://i.imgur.com/example.png) <!-- Optional: Add a link to a screenshot or GIF of the bot in action -->

## ✨ Features

-   **Multi-File Muxing**: Combine one video file, one audio file, and multiple subtitle tracks.
-   **Intelligent Anime Naming**: Automatically parses anime filenames using `Anitopy` to generate clean, professional output names (e.g., `[SubsPlease] My Anime - 01 (1080p) [F00B4B5A].mkv` becomes `My Anime - S01E01 [1080p].mkv`).
-   **Flexible Thumbnail Support**:
    -   Upload a custom image to use as the thumbnail.
    -   If no thumbnail is provided, one is automatically generated from the video.
-   **Metadata Control**: Add language and title metadata specifically to the *new* audio track using a simple command.
-   **Stream Copy**: Uses FFmpeg's `-c copy` flag for all operations, ensuring the fastest possible muxing with no loss of quality. Preserves all original video and audio tracks.
-   **User-Friendly Workflow**: A stateful process guides the user from file submission to the final mux command.
-   **Robust & Isolated**: Each user's files are handled in a separate temporary directory to prevent conflicts. All files are cleaned up automatically after each session.
-   **Dockerized**: Comes with a `Dockerfile` for easy, reproducible, and isolated deployment. All dependencies (including FFmpeg) are handled within the container.

## Prerequisites

-   [**Docker**](https://www.docker.com/get-started/) installed and running on your system.
-   A **Telegram Account**.

## 🚀 Setup & Deployment

Follow these steps to get your bot up and running in minutes.

### 1. Clone or Download the Project

First, get the project files onto your machine.

```bash
git clone https://your-repo-link.com/muxer-bot.git
cd muxer-bot
