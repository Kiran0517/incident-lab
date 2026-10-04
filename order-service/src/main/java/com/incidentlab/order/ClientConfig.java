package com.incidentlab.order;

import java.net.http.HttpClient;
import java.time.Duration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

@Configuration
public class ClientConfig {

    /**
     * One shared JDK HttpClient with a connection pool (HTTP/1.1 keep-alive).
     * Previously each call used HttpURLConnection, which keeps very few idle
     * connections per host. Under ~2,600 req/s that caused constant new TCP
     * connections, TIME_WAIT buildup, and ephemeral port exhaustion
     * ("Cannot assign requested address").
     */
    @Bean
    public HttpClient pooledHttpClient() {
        return HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(2))
                .build();
    }

    @Bean
    public RestClient inventoryClient(RestClient.Builder builder,
                                      HttpClient pooledHttpClient,
                                      @Value("${services.inventory.url}") String baseUrl,
                                      @Value("${services.http.read-timeout-ms}") int readTimeoutMs) {
        return builder.baseUrl(baseUrl).requestFactory(factory(pooledHttpClient, readTimeoutMs)).build();
    }

    @Bean
    public RestClient paymentClient(RestClient.Builder builder,
                                    HttpClient pooledHttpClient,
                                    @Value("${services.payment.url}") String baseUrl,
                                    @Value("${services.http.read-timeout-ms}") int readTimeoutMs) {
        return builder.baseUrl(baseUrl).requestFactory(factory(pooledHttpClient, readTimeoutMs)).build();
    }

    /** Explicit read timeout: a slow dependency must not hang order-service threads forever. */
    private static JdkClientHttpRequestFactory factory(HttpClient client, int readTimeoutMs) {
        JdkClientHttpRequestFactory f = new JdkClientHttpRequestFactory(client);
        f.setReadTimeout(Duration.ofMillis(readTimeoutMs));
        return f;
    }
}
