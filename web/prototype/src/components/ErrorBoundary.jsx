import { Component } from "react";
import { Button, Text, Title } from "@mantine/core";

// A render-time crash anywhere below this (a malformed job report, a
// layout envelope missing a field the edit surface assumed was there)
// used to take down the whole app with a blank white screen -- this is
// the one thing MOCK mode's fixtures never exercised, since they're
// hand-shaped to match every consumer exactly. Real server responses
// have no such guarantee.
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("palimpsest: render error", error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div style={{ maxWidth: 480, margin: "80px auto", padding: "0 24px", textAlign: "center" }}>
        <Title order={2} style={{ fontSize: 20 }}>
          Something went wrong rendering this screen
        </Title>
        <Text c="dimmed" size="sm" mt={10}>
          {this.state.error.message || String(this.state.error)}
        </Text>
        <Button mt={20} onClick={() => window.location.reload()}>
          Reload
        </Button>
      </div>
    );
  }
}
