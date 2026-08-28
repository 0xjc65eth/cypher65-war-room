import { Component, type ErrorInfo, type ReactNode } from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { theme } from '../theme';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('CYPHER65 ErrorBoundary caught an error:', error, errorInfo);
  }

  reset = () => {
    this.setState({ hasError: false, error: undefined });
  };

  render() {
    if (this.state.hasError) {
      return (
        <View style={styles.container}>
          <Text style={styles.heading}>Something went wrong</Text>
          <Text style={styles.message}>{this.state.error?.message || 'Unknown error'}</Text>
          <TouchableOpacity style={styles.button} onPress={this.reset}>
            <Text style={styles.buttonText}>Try again</Text>
          </TouchableOpacity>
        </View>
      );
    }
    return this.props.children;
  }
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.bg.deep,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
  heading: {
    color: theme.red.DEFAULT,
    fontSize: 20,
    fontWeight: '700',
    marginBottom: 12,
  },
  message: {
    color: theme.text.tertiary,
    fontSize: 14,
    textAlign: 'center',
    marginBottom: 24,
  },
  button: {
    backgroundColor: theme.bg.brand,
    borderRadius: 8,
    paddingHorizontal: 24,
    paddingVertical: 12,
  },
  buttonText: {
    color: theme.text.onBrand,
    fontWeight: '600',
  },
});
