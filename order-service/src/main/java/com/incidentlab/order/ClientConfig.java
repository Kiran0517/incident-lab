package com.incidentlab.order;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

@Configuration
public class ClientConfig {

    @Bean
    public RestClient inventoryClient(RestClient.Builder builder,
                                      @Value("${services.inventory.url}") String baseUrl,
                                      @Value("${services.http.read-timeout-ms}") int readTimeoutMs) {
        return builder.baseUrl(baseUrl).requestFactory(factory(readTimeoutMs)).build();
    }

    @Bean
    public RestClient paymentClient(RestClient.Builder builder,
                                    @Value("${services.payment.url}") String baseUrl,
                                    @Value("${services.http.read-timeout-ms}") int readTimeoutMs) {
        return builder.baseUrl(baseUrl).requestFactory(factory(readTimeoutMs)).build();
    }

    /** Explicit timeouts: without them a slow dependency would hang order-service threads forever. */
    private static SimpleClientHttpRequestFactory factory(int readTimeoutMs) {
        SimpleClientHttpRequestFactory f = new SimpleClientHttpRequestFactory();
        f.setConnectTimeout(2000);
        f.setReadTimeout(readTimeoutMs);
        return f;
    }
}
