// Initialize Mermaid with custom configuration for better visualization
document.addEventListener('DOMContentLoaded', function() {
    mermaid.initialize({
        startOnLoad: true,
        securityLevel: 'loose',
        theme: 'default',
        flowchart: {
            useMaxWidth: false,
            htmlLabels: true,
            curve: 'basis',
            padding: 20,
            nodeSpacing: 50,
            rankSpacing: 80
        }
    });
});
