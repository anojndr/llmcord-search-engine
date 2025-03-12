"""
Discord UI Module

This module contains UI components for Discord interaction,
including views, modals, and buttons for user interaction.
"""

import io
import logging
from typing import List, Dict, Optional

import discord
from discord import File
from discord.ui import Button, TextInput

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class ImageCountModal(discord.ui.Modal, title="Select Number of Images"):
    """
    Modal for selecting the number of images to display.
    """
    
    def __init__(self, parent_view: 'OutputView') -> None:
        """
        Initialize the modal with a reference to its parent view.
        
        Args:
            parent_view: The parent OutputView instance
        """
        super().__init__()
        self.parent_view = parent_view

        self.image_count = TextInput(
            label="Number of images per query",
            placeholder="Enter a number between 1 and 5",
            default="5",
            min_length=1,
            max_length=1,
            required=True
        )
        self.add_item(self.image_count)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """
        Handle modal submission, validating user input.
        
        Args:
            interaction: The Discord interaction
        """
        try:
            count: int = int(self.image_count.value)
            if 1 <= count <= 5:
                logger.info(
                    f"User {interaction.user.name} ({interaction.user.id}) "
                    f"selected {count} images per query"
                )
                await self.parent_view.show_images(interaction, count)
            else:
                logger.warning(
                    f"User {interaction.user.name} ({interaction.user.id}) "
                    f"entered invalid image count: {count}"
                )
                await interaction.response.send_message(
                    "Please enter a number between 1 and 5.",
                    ephemeral=True
                )
        except ValueError:
            logger.warning(
                f"User {interaction.user.name} ({interaction.user.id}) "
                f"entered non-numeric image count: {self.image_count.value}"
            )
            await interaction.response.send_message(
                "Please enter a valid number between 1 and 5.",
                ephemeral=True
            )


class OutputView(discord.ui.View):
    """
    View for displaying output with interactive buttons.
    
    Attributes:
        contents: Text content to display
        query: Original query that produced this output
        serper_queries: Search queries used (if any)
        image_files: Dictionary mapping queries to image files
        image_urls: Dictionary mapping queries to image URLs
    """
    
    def __init__(
        self,
        contents: List[str],
        query: str,
        serper_queries: Optional[List[str]] = None,
        image_files: Optional[Dict[str, List[File]]] = None,
        image_urls: Optional[Dict[str, List[str]]] = None
    ) -> None:
        """
        Initialize the view with content and optional image data.
        
        Args:
            contents: Text content to display
            query: Original query that produced this output
            serper_queries: Search queries used (if any)
            image_files: Dictionary mapping queries to image files
            image_urls: Dictionary mapping queries to image URLs
        """
        super().__init__(timeout=None)
        self.contents = contents if isinstance(contents, list) else [contents]
        self.query = query
        self.serper_queries = serper_queries
        self.image_files = image_files or {}
        self.image_urls = image_urls or {}

        self.add_text_file_button()
        if self.serper_queries and (self.image_files or self.image_urls):
            self.add_show_images_button()
            
        logger.debug(
            f"Created OutputView with query: '{query[:50]}...', "
            f"{len(self.image_files)} image file sets, "
            f"{len(self.image_urls)} image URL sets"
        )

    def add_text_file_button(self) -> None:
        """Add a button to get the output as a text file."""
        text_file_button: Button = Button(
            label="Get Output as Text File",
            style=discord.ButtonStyle.primary,
            custom_id="text_file"
        )
        text_file_button.callback = self.text_file_button_callback
        self.add_item(text_file_button)

    def add_show_images_button(self) -> None:
        """Add a button to show images if available."""
        show_images_button: Button = Button(
            label="Show Images",
            style=discord.ButtonStyle.secondary,
            custom_id="show_images"
        )
        show_images_button.callback = self.show_images_button_callback
        self.add_item(show_images_button)

    async def text_file_button_callback(self, interaction: discord.Interaction) -> None:
        """
        Handle click on the text file button.
        
        Args:
            interaction: The Discord interaction
        """
        logger.info(
            f"Text file button clicked by user {interaction.user.name} "
            f"({interaction.user.id})"
        )
        await self.send_text_file(interaction)
        
        # Disable the button after use
        for item in self.children:
            if hasattr(item, 'custom_id') and item.custom_id == "text_file":
                item.disabled = True
                break
                
        await interaction.message.edit(view=self)

    async def show_images_button_callback(self, interaction: discord.Interaction) -> None:
        """
        Handle click on the show images button.
        
        Args:
            interaction: The Discord interaction
        """
        total_images: int = (
            sum(len(files) for files in self.image_files.values()) + 
            sum(len(urls) for urls in self.image_urls.values())
        )

        logger.info(
            f"Show images button clicked by user {interaction.user.name} "
            f"({interaction.user.id}), total images: {total_images}"
        )

        if total_images == 0:
            logger.warning("No images found when 'Show Images' button was clicked")
            await interaction.response.send_message("No images found.", ephemeral=True)
            return

        # Show modal to select image count
        modal: ImageCountModal = ImageCountModal(self)
        await interaction.response.send_modal(modal)
        
        # Disable the button after use
        for item in self.children:
            if hasattr(item, 'custom_id') and item.custom_id == "show_images":
                item.disabled = True
                break
                
        await interaction.message.edit(view=self)

    async def send_text_file(self, interaction: discord.Interaction) -> None:
        """
        Send the output as a text file.
        
        Args:
            interaction: The Discord interaction
        """
        try:
            full_content: str = "".join(self.contents)
            file = io.StringIO(full_content)
            await interaction.response.send_message(
                content="Here is the output as a text file:",
                file=File(file, filename="output.txt"),
                ephemeral=True
            )
            logger.info(
                f"Text file sent to user {interaction.user.name} "
                f"({interaction.user.id})"
            )
        except Exception as e:
            logger.error(
                f"Error sending text file to user {interaction.user.name} "
                f"({interaction.user.id}): {e}", 
                exc_info=True
            )
            await interaction.response.send_message(
                "An error occurred while generating the text file.",
                ephemeral=True
            )

    async def show_images(self, interaction: discord.Interaction, selected_count: int) -> None:
        """
        Show selected images based on user count choice.
        
        Args:
            interaction: The Discord interaction
            selected_count: Number of images to show per query
        """
        try:
            await interaction.response.defer()
            logger.info(
                f"Showing {selected_count} images per query for user "
                f"{interaction.user.name} ({interaction.user.id})"
            )

            # Handle single query case without serper_queries
            if len(self.image_files) == 1 and not self.serper_queries:
                await self._handle_single_query_images(interaction, selected_count)
            else:
                # Handle multiple queries case
                await self._handle_multiple_query_images(interaction, selected_count)
                
        except Exception as e:
            logger.error(
                f"Error showing images to user {interaction.user.name} "
                f"({interaction.user.id}): {e}", 
                exc_info=True
            )
            await interaction.followup.send(
                "An error occurred while showing images.",
                ephemeral=True
            )
    
    async def _handle_single_query_images(
        self, 
        interaction: discord.Interaction, 
        selected_count: int
    ) -> None:
        """
        Handle displaying images for a single query case.
        
        Args:
            interaction: The Discord interaction
            selected_count: Number of images to show per query
        """
        query: str = next(iter(self.image_files))
        files: List[File] = (
            self.image_files[query][:selected_count] 
            if self.image_files[query] else []
        )
        urls: List[str] = (
            self.image_urls[query][:selected_count] 
            if query in self.image_urls else []
        )
        
        if not files and not urls:
            logger.warning(f"No images available for query: {query}")
            await interaction.followup.send("No images available.", ephemeral=True)
            return
        
        message_content: str = f"Here are {len(files) + len(urls)} images:"
        if urls:
            message_content += "\n\nFailed downloads (shown as URLs):\n" + "\n".join(urls)
        
        await interaction.followup.send(content=message_content, files=files)
        logger.info(f"Sent {len(files)} images and {len(urls)} URLs for single query")
    
    async def _handle_multiple_query_images(
        self, 
        interaction: discord.Interaction, 
        selected_count: int
    ) -> None:
        """
        Handle displaying images for multiple queries.
        
        Args:
            interaction: The Discord interaction
            selected_count: Number of images to show per query
        """
        for i, query in enumerate(self.image_files.keys(), 1):
            files: List[File] = (
                self.image_files[query][:selected_count] 
                if query in self.image_files else []
            )
            urls: List[str] = (
                self.image_urls[query][:selected_count] 
                if query in self.image_urls else []
            )
            
            if not files and not urls:
                logger.debug(f"Skipping query with no images: {query}")
                continue
            
            message_content: str = (
                f"Images for query {i}: '{query}' "
                f"({len(files) + len(urls)} images)"
            )
            if urls:
                message_content += "\n\nFailed downloads (shown as URLs):\n" + "\n".join(urls)
            
            await interaction.followup.send(content=message_content, files=files)
            logger.info(
                f"Sent {len(files)} images and {len(urls)} URLs for query {i}: "
                f"'{query}'"
            )