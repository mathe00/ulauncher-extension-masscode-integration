# 📄 Ulauncher Plugin/Extension MassCode Integration

👋 **Welcome to the Ulauncher Plugin/Extension MassCode Integration repository!**

This plugin/extension allows you to easily access your **[MassCode](https://masscode.io) snippets** directly from **[Ulauncher](https://ulauncher.io)**. No need to manually open MassCode or browse through folders to find your snippets anymore. Just type the snippet name or part of it in Ulauncher, and boom – access it instantly! 🚀

## 🚀 Features Available

- 🔍 **Quick snippet search**: Type a keyword in Ulauncher to search through your MassCode snippets.
- 📂 **Choose database path**: You can specify the path to the JSON file containing your MassCode snippets.
- 📄 **Snippet preview**: View the content of your snippets directly in Ulauncher.
- 🌟 **Personalized contextual autocomplete**: The extension intelligently prioritizes snippets based on your usage patterns.
- ✨ **NEW! Smart Single Result**: Optionally, if a snippet overwhelmingly dominates your selections for a specific query, the extension can show only that snippet.
- ⏩ **Quick access**: Choose between copying the snippet to your clipboard or pasting it directly (okay, the pasting option isn't functional yet, but one day... maybe?).

## 🆕 What's New (Recent Update)

We've rolled out updates to enhance your productivity:

### 🌟 Personalized Contextual Autocomplete

- The extension learns from your search patterns and selections to prioritize the snippets you frequently use in specific contexts.
- When you search with a term similar to previous searches, snippets you've selected before will be marked with a star (★) and appear higher in results.
- The system is smart enough to only boost results when your current search is contextually relevant to your history.

### ✨ Smart Single Result (Optional)

- **Purpose**: To streamline results when you consistently pick the same snippet for a particular search query.
- **How it works**: If, for a specific search term, one snippet has been chosen a significantly high percentage of the time (e.g., you've picked "my_ssh_key" 9 out of 10 times when searching "ssh"), the extension can be configured to display *only* that dominant snippet.
- **Configuration**:
    - Go to Ulauncher Preferences -> Extensions -> MassCode Snippets.
    - Find the "Smart Single Result Ratio (0.0-1.0)" setting.
    - Set a value between 0.0 and 1.0. For example:
        - `0.0` (Default): Disables the feature.
        - `0.75`: If a snippet accounts for 75% or more of selections for a query, it will be the sole result.
        - `0.9`: Requires 90% dominance.
        - `1.0`: Requires 100% dominance (the snippet was the *only* one ever picked for that query).
    - This feature requires "Enable Contextual Learning" to be active.
- **Benefit**: Reduces clutter and speeds up access to your most-used snippets in familiar contexts.

### 📊 How Contextual Features Work

1. The extension tracks which snippets you select with specific search queries (if contextual learning is enabled).
2. When you search again using the same or similar terms, the system recognizes the context.
3. Snippets you've selected before in similar contexts get a relevance boost (contextual autocomplete).
4. If the "Smart Single Result" feature is enabled and its ratio threshold is met for the current query, only the dominant snippet is shown.
5. The algorithm uses both exact matching and fuzzy matching with gradual relevance scoring.
6. Your most frequently used snippets for specific search patterns rise to the top.

### 🎯 Precision Focus

Unlike overly aggressive autocomplete systems that suggest the same items regardless of context, our implementation:
- Only prioritizes items when truly relevant to your current search.
- Maintains a balance between historical preferences and textual relevance.
- Provides visual indicators (★) so you know when items are being contextually boosted.

## 🛠️ Installation

To install and try out the **Ulauncher Plugin/Extension MassCode Integration**, follow these steps:

1. Clone this repository or download it as a ZIP file.
2. In your terminal, navigate to your Ulauncher extensions folder. The path is typically `~/.local/share/ulauncher/extensions/`. If a `masscode-snippet` subfolder doesn't exist, create it.
   ```bash
   mkdir -p ~/.local/share/ulauncher/extensions/masscode-snippet/
   cd ~/.local/share/ulauncher/extensions/masscode-snippet/
   ```
3. Clone this repository into the `masscode-snippet` folder or move the downloaded files there:
   ```bash
   # If you are inside masscode-snippet folder already:
   git clone https://github.com/mathe00/ulauncher-extension-masscode-integration.git .
   # Or, if you downloaded and extracted, copy files here.
   ```
4. Before restarting Ulauncher, install the required dependencies by running:
   ```bash
   # Ensure you are in the masscode-snippet extension directory
   # Create a libs folder if it doesn't exist
   mkdir -p libs
   pip install -r requirements.txt -t libs/
   ```
5. Restart **[Ulauncher](https://ulauncher.io)**.

6. **Important:** After installation, it is highly recommended to configure the settings for the extension. Open Ulauncher, navigate to the extensions section, and adjust the preferences for the MassCode plugin/extension. This includes setting the path to your MassCode database, enabling contextual learning, and configuring the new "Smart Single Result Ratio".

That's it! The plugin/extension is now installed, and you can start searching your MassCode snippets directly from **[Ulauncher](https://github.com/Ulauncher/Ulauncher)**.

## 🖼️ Screenshots

Here are some examples of how the Ulauncher Plugin/Extension MassCode Integration works:

*(Screenshots would show the extension in action, potentially highlighting the star icon for contextual results and an example of a single smart result if applicable)*
<!--
<img src="https://github.com/user-attachments/assets/11c427c6-7472-4177-a515-d30e595d0acd" alt="image" width="500"/>
<img src="https://github.com/user-attachments/assets/9ae7e59b-cf36-4c51-802a-6512d550649b" alt="image" width="500"/>
-->
*Feel free to include your own screenshots to showcase how the plugin/extension works in action!*

## 🧠 Technical Details

For the curious developers out there, our autocomplete and smart result systems implement:

- Context-specific selection history tracking via a JSON-based storage system.
- Graduated relevance scoring with different thresholds for exact, prefix, and fuzzy matches.
- Optional single-result filtering based on a configurable selection dominance ratio.
- Optimized performance with limited result counts and efficient matching algorithms.
- Comprehensive error handling and logging for better debugging.
- Type hints and modular code structure for easier maintenance and future expansion.

The implementation balances user personalization with search precision - ensuring that contextual boosts and smart filtering only occur when meaningful, while maintaining the extension's responsive performance.

## ✨ New: Ulauncher Plugin/Extension Text Tools

If you're interested in more text transformations, check out my latest **[Text Tools plugin/extension](https://github.com/mathe00/ulauncher-plugin-text-tools)**! This new extension allows you to transform any input text into various formats such as Uppercase, CamelCase, Snake Case, and even SpongeBob Case (yes, that's a thing!). You can easily toggle these transformations from the Ulauncher settings, making it a super versatile and complete tool for text manipulation. 💡

## 🛠️ Contributing

I've got to be honest – this plugin/extension was developed mostly thanks to **ChatGPT** helping me along the way! 😅 I haven't actively developed it much recently because, well, it works for me, and I'm lazy. But, I'm also a huge fan of **features and customization**, so I'm always open to **feedback, recommendations, and pull requests**.

I built this for myself, but I figured others might also find it useful. So here it is, shared with the world. 🌍

Feel free to open issues or submit pull requests if you have ideas on how to improve it. Contributions are always welcome!

Oh, and **English isn't my first language**, so I apologize if I misunderstand something or take a bit longer to respond to issues or pull requests 😅. Thanks for your patience!

## ⚖️ License

I've added the **MIT License** because it's the most permissive and simple, but I'm not 100% sure it's the right one for this project. If there's a different license I should be using (especially regarding **Ulauncher** or **MassCode**), **please let me know**! I definitely don't want to cause any issues with these amazing tools – I just want to share what I've built in case it helps others. 😊

## 🙏 Special Thanks

A huge shout-out to the amazing developers of **[Ulauncher](https://ulauncher.io)** – hands down, the best application launcher in the universe for Linux! 🚀 You guys rock! And a big thank you to the team behind **[MassCode](https://masscode.io)** for building such a cool and powerful snippet manager. You've made coding life so much easier!

## ⭐ Show Your Support

I'm not really concerned about the number of stars, but if you find this project useful or interesting, consider giving it a star on GitHub to help me gauge the interest. If you'd rather not leave a star, that's totally fine – feel free to open an issue, submit a pull request, or even drop a message of support in an issue instead! All kinds of feedback, advice, and contributions are always welcome and appreciated. 😊