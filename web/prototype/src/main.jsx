import React from "react";
import ReactDOM from "react-dom/client";
import "@mantine/core/styles.css";
import "@mantine/tiptap/styles.css";
import "@mantine/notifications/styles.css";
import "@mantine/dropzone/styles.css";
import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { theme } from "./theme.js";
import { I18nProvider } from "./i18n.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import "./index.css";
import App from "./App.jsx";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="dark">
      <I18nProvider>
        <Notifications position="bottom-center" />
        <ErrorBoundary>
          <App />
        </ErrorBoundary>
      </I18nProvider>
    </MantineProvider>
  </React.StrictMode>,
);
