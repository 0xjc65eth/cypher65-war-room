import { useRef, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TextInput,
  TouchableOpacity,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
} from 'react-native';
import axios from 'axios';
import { AiOperatorResponseError, queryAiOperator } from '../../api/client';
import { theme } from '../../theme';

interface ChatMessage {
  id: string;
  role: 'user' | 'ai';
  text: string;
  ts: number;
}

/**
 * AI Operator screen.
 *
 * Responses are displayed only after the authenticated backend completes its
 * `POST /api/ai/query` SSE response. Backend and protocol failures remain
 * explicit; the mobile app never fabricates an assistant response.
 */
export const AiOperatorScreen = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<FlatList<ChatMessage>>(null);
  const sendingRef = useRef(false);

  const appendMessage = (message: ChatMessage) => {
    setMessages((prev) => [...prev, message]);
  };

  const errorMessage = (cause: unknown): string => {
    if (axios.isAxiosError(cause)) {
      if (cause.response?.status === 401) return 'Your session expired. Sign in again.';
      if (cause.response?.status === 402) return 'AI Operator requires an active Premium license.';
      if (cause.response?.status === 429) return 'AI Operator rate limit reached. Try again later.';
      return 'AI Operator is unavailable. Check the server connection and configuration.';
    }
    if (cause instanceof AiOperatorResponseError) return cause.message;
    return 'AI Operator is unavailable. No response was generated.';
  };

  const sendMessage = async () => {
    const query = input.trim();
    if (!query || sendingRef.current) return;
    sendingRef.current = true;

    const userMessage: ChatMessage = {
      id: `${Date.now()}_u`,
      role: 'user',
      text: query,
      ts: Date.now(),
    };

    appendMessage(userMessage);
    setInput('');
    setError(null);
    setSending(true);

    try {
      const response = await queryAiOperator(userMessage.text);

      const aiResponse: ChatMessage = {
        id: `${Date.now()}_a`,
        role: 'ai',
        text: response,
        ts: Date.now(),
      };
      appendMessage(aiResponse);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      sendingRef.current = false;
      setSending(false);
      listRef.current?.scrollToEnd({ animated: true });
    }
  };

  const renderItem = ({ item }: { item: ChatMessage }) => (
    <View
      style={[
        styles.bubble,
        item.role === 'user' ? styles.userBubble : styles.aiBubble,
      ]}
    >
      <Text style={item.role === 'user' ? styles.userText : styles.aiText}>{item.text}</Text>
    </View>
  );

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      keyboardVerticalOffset={90}
    >
      <FlatList
        ref={listRef}
        style={styles.list}
        data={messages}
        keyExtractor={(item) => item.id}
        renderItem={renderItem}
        contentContainerStyle={styles.listContent}
        ListEmptyComponent={
          <Text style={styles.hint}>
            Ask the CYPHER65 AI Operator anything about your fleet, block probability, or market.
          </Text>
        }
      />
      {error ? (
        <View style={styles.errorPanel} accessibilityRole="alert" testID="ai-operator-error">
          <Text style={styles.errorTitle}>AI Operator unavailable</Text>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      ) : null}
      <View style={styles.inputRow}>
        <TextInput
          style={styles.input}
          placeholder="Type a command..."
          placeholderTextColor={theme.text.secondary}
          value={input}
          onChangeText={setInput}
          onSubmitEditing={sendMessage}
          editable={!sending}
          accessibilityLabel="Question for AI Operator"
        />
        <TouchableOpacity
          style={[styles.sendButton, sending && styles.sendButtonDisabled]}
          onPress={sendMessage}
          disabled={sending}
          accessibilityRole="button"
          accessibilityLabel="Send question"
          accessibilityState={{ disabled: sending, busy: sending }}
        >
          {sending ? <ActivityIndicator color={theme.text.onBrand} /> : <Text style={styles.sendText}>Send</Text>}
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.bg.deep,
  },
  list: {
    flex: 1,
    padding: 16,
  },
  listContent: {
    paddingBottom: 8,
  },
  bubble: {
    borderRadius: 12,
    padding: 12,
    marginVertical: 4,
    maxWidth: '80%',
  },
  userBubble: {
    alignSelf: 'flex-end',
    backgroundColor: theme.bg.brand,
  },
  aiBubble: {
    alignSelf: 'flex-start',
    backgroundColor: theme.bg.elevated,
  },
  userText: {
    color: theme.text.onBrand,
  },
  aiText: {
    color: theme.text.faint,
  },
  hint: {
    color: theme.text.secondary,
    textAlign: 'center',
    marginTop: 24,
    fontStyle: 'italic',
  },
  errorPanel: {
    marginHorizontal: 12,
    marginBottom: 4,
    padding: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.red.DEFAULT,
    backgroundColor: theme.bg.surface,
  },
  errorTitle: {
    color: theme.red.DEFAULT,
    fontWeight: '700',
    marginBottom: 4,
  },
  errorText: {
    color: theme.text.primary,
  },
  inputRow: {
    flexDirection: 'row',
    padding: 12,
    backgroundColor: theme.bg.surface,
    alignItems: 'center',
  },
  input: {
    flex: 1,
    backgroundColor: theme.bg.elevated,
    color: theme.text.primary,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    marginRight: 8,
  },
  sendButton: {
    backgroundColor: theme.bg.brand,
    borderRadius: 8,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  sendButtonDisabled: {
    opacity: 0.65,
  },
  sendText: {
    color: theme.text.onBrand,
    fontWeight: '600',
  },
});
